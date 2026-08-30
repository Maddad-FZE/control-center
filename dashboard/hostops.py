"""Host reboot, Docker container restart, and USB device listing."""

import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

import docker
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CONTAINER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,126}$")
USB_DEVICE_RE = re.compile(r"^\d+-\d+(\.\d+)*$")
BLOCK_NAME_RE = re.compile(r"^(sd[a-z]+|mmcblk\d+|nvme\d+n\d+)$")
REBOOT_LOCK_KEY = "host:reboot_lock"
REBOOT_LOCK_TTL = 90
UNMOUNT_PREFIXES = (
    "/media/",
    "/mnt/",
    "/run/media/",
    "/host/media/",
    "/host/mnt/",
)
USB_CLASS_LABELS = {
    "01": "Audio",
    "02": "Communications",
    "03": "HID",
    "08": "Storage",
    "09": "Hub",
    "0a": "CDC",
    "0e": "Video",
    "e0": "Wireless",
    "ef": "Misc",
    "ff": "Vendor",
}
USB_SPEED_LABELS = {
    "1.5": "USB 1.1",
    "12": "USB 1.1",
    "480": "USB 2.0",
    "5000": "USB 3.0",
    "10000": "USB 3.1",
    "20000": "USB 3.2",
}


def _docker_client():
    return docker.DockerClient(base_url=settings.DOCKER_HOST)


def _read_sysfs(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def usb_sysfs_root():
    candidates = []
    configured = (getattr(settings, "USB_SYSFS_ROOT", "") or "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        (
            Path("/host/sys/bus/usb/devices"),
            Path("/host/sys/bus/usb"),
            Path("/sys/bus/usb/devices"),
            Path("/sys/bus/usb"),
        )
    )
    for root in candidates:
        if (root / "devices").is_dir():
            return root / "devices"
        if root.is_dir():
            return root
    return None


def _usb_kind(dev_dir, device_class):
    classes = set()
    if device_class and device_class != "00":
        classes.add(device_class.lower())
    for child in dev_dir.iterdir():
        if not child.is_dir() or ":" not in child.name:
            continue
        iface = _read_sysfs(child / "bInterfaceClass")
        if iface:
            classes.add(iface.lower())
    if "08" in classes:
        return "Storage"
    if "03" in classes:
        return "HID"
    if "0e" in classes:
        return "Video"
    if "01" in classes:
        return "Audio"
    if "02" in classes or "0a" in classes:
        return "Serial"
    if "09" in classes and len(classes) == 1:
        return "Hub"
    if classes:
        first = sorted(classes)[0]
        return USB_CLASS_LABELS.get(first, "USB")
    return "USB"


def _block_devices(dev_dir):
    names = []
    try:
        for path in dev_dir.glob("**/block/*"):
            if path.is_dir() and BLOCK_NAME_RE.match(path.name):
                names.append(path.name)
    except OSError:
        return []
    return sorted(set(names))


def _parse_mounts():
    rows = []
    for mounts_file in (Path("/host/proc/mounts"), Path("/proc/mounts")):
        if not mounts_file.is_file():
            continue
        try:
            text = mounts_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                rows.append((parts[0], parts[1].replace("\\040", " ")))
        if rows:
            break
    return rows


def _mounts_for_blocks(block_names):
    if not block_names:
        return []
    prefixes = tuple(f"/dev/{name}" for name in block_names)
    out = []
    seen = set()
    for device, mount in _parse_mounts():
        if any(device == prefix or device.startswith(prefix) for prefix in prefixes):
            key = (device, mount)
            if key in seen:
                continue
            seen.add(key)
            out.append({"device": device, "path": mount})
    return out


def list_usb_devices():
    root = usb_sysfs_root()
    if root is None:
        return {
            "available": False,
            "devices": [],
            "message": "USB sysfs is not mounted. Bind /sys/bus/usb into the container.",
        }
    devices = []
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        return {"available": False, "devices": [], "message": str(exc)[:200]}
    for dev_dir in entries:
        if not dev_dir.is_dir() or not USB_DEVICE_RE.match(dev_dir.name):
            continue
        vendor = _read_sysfs(dev_dir / "idVendor")
        product = _read_sysfs(dev_dir / "idProduct")
        if not vendor or not product:
            continue
        manufacturer = _read_sysfs(dev_dir / "manufacturer")
        product_name = _read_sysfs(dev_dir / "product")
        serial = _read_sysfs(dev_dir / "serial")
        speed = _read_sysfs(dev_dir / "speed")
        device_class = _read_sysfs(dev_dir / "bDeviceClass")
        kind = _usb_kind(dev_dir, device_class)
        blocks = _block_devices(dev_dir)
        mounts = _mounts_for_blocks(blocks)
        label = " ".join(part for part in (manufacturer, product_name) if part) or f"{vendor}:{product}"
        devices.append(
            {
                "id": dev_dir.name,
                "name": label,
                "vendor_id": vendor,
                "product_id": product,
                "serial": serial,
                "kind": kind,
                "speed": USB_SPEED_LABELS.get(speed, f"{speed} Mb/s" if speed else ""),
                "blocks": blocks,
                "mounts": mounts,
            }
        )
    devices.sort(key=lambda row: (row["kind"] != "Storage", row["name"].lower(), row["id"]))
    return {"available": True, "devices": devices, "message": ""}


def unmount_path(mount_path):
    path = (mount_path or "").strip()
    if not path.startswith("/") or ".." in path.split("/"):
        return False, "Invalid mount path."
    allowed = path in ("/media", "/mnt") or path.startswith(UNMOUNT_PREFIXES)
    if not allowed:
        return False, "That mount is not a removable path."
    if not Path(path).is_dir():
        return False, "That path is not mounted here."
    umount = shutil.which("umount")
    if not umount:
        return False, "umount is not available in this environment."
    try:
        result = subprocess.run(
            [umount, path],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)[:200]
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "umount failed").strip()
        return False, err[:200]
    return True, f"Unmounted {path}."


def restart_container(name):
    name = (name or "").strip().lstrip("/")
    if not CONTAINER_NAME_RE.match(name):
        return False, "Invalid container name."
    try:
        client = _docker_client()
        container = client.containers.get(name)
        container.restart(timeout=20)
    except docker.errors.NotFound:
        return False, "Container not found."
    except Exception as exc:
        logger.warning("Container restart failed for %s: %s", name, exc)
        return False, str(exc)[:200]
    cache.delete("docker:containers")
    return True, f"Restarted {name}."


def _spawn_command(command):
    try:
        if isinstance(command, (list, tuple)):
            subprocess.Popen(
                list(command),
                cwd="/",
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                command,
                cwd="/",
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=True,
            )
    except OSError as exc:
        return False, str(exc)[:200]
    return True, "Reboot scheduled."


def _try_sysrq():
    trigger = Path("/proc/sysrq-trigger")
    if not trigger.exists():
        return False
    try:
        trigger.write_text("b", encoding="ascii")
        return True
    except OSError:
        return False


def _reboot_via_docker():
    try:
        client = _docker_client()
    except Exception as exc:
        return False, str(exc)[:200]
    image = None
    hostname = os.environ.get("HOSTNAME", "")
    for name in (hostname, "control-center"):
        if not name:
            continue
        try:
            container = client.containers.get(name)
            image = (container.image.tags[0] if container.image.tags else container.image.id)
            break
        except Exception:
            continue
    if not image:
        return False, "Could not find a local image for the reboot helper."
    code = (
        "from pathlib import Path\n"
        "sysrq = Path('/proc/sys/kernel/sysrq')\n"
        "if sysrq.exists():\n"
        "    sysrq.write_text('1')\n"
        "Path('/proc/sysrq-trigger').write_text('b')\n"
    )
    try:
        client.containers.run(
            image,
            command=["python", "-c", code],
            privileged=True,
            detach=True,
            remove=True,
            network_mode="none",
        )
    except Exception as exc:
        logger.warning("Docker reboot helper failed: %s", exc)
        return False, str(exc)[:200]
    return True, "Reboot scheduled."


def _reboot_now():
    command = (getattr(settings, "HOST_REBOOT_COMMAND", "") or "").strip()
    if command:
        ok, message = _spawn_command(command)
        if ok:
            return
        logger.warning("HOST_REBOOT_COMMAND failed: %s", message)
    if _try_sysrq():
        return
    for binary in ("systemctl", "reboot", "shutdown"):
        path = shutil.which(binary)
        if not path:
            continue
        args = [path, "reboot"] if binary == "systemctl" else [path, "-r", "now"] if binary == "shutdown" else [path]
        ok, message = _spawn_command(args)
        if ok:
            return
        logger.warning("reboot via %s failed: %s", binary, message)
    ok, message = _reboot_via_docker()
    if not ok:
        logger.error("Host reboot failed: %s", message)


def schedule_reboot():
    """Queue a host reboot after the HTTP response can return."""
    if not cache.add(REBOOT_LOCK_KEY, "1", REBOOT_LOCK_TTL):
        return False, "A reboot is already in progress."
    threading.Timer(2.0, _reboot_now).start()
    return True, "The Pi will reboot in a few seconds."
