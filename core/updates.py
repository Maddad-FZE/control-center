"""Version checking against GitHub Releases and in-place archive installs."""

import logging
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import UpdateStatus, log_audit
from .version import clear_version_cache, get_current_version

logger = logging.getLogger(__name__)

GITHUB_API_ROOT = "https://api.github.com"
CHECK_LOCK_KEY = "update:check_lock"
CHECK_LOCK_TTL = 120
INSTALL_LOCK_KEY = "update:install_lock"
INSTALL_LOCK_TTL = 60
STALE_INSTALL_GRACE_SECONDS = 120
LOCK_HEARTBEAT_SECONDS = 15
REQUEST_TIMEOUT = 10
TAG_PATTERN = re.compile(r"^v?\d+(\.\d+){0,3}$")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NO_RELEASES_MESSAGE = "No releases published yet."
DOWNLOAD_TIMEOUT = 300
DOWNLOAD_CHUNK = 1024 * 64
ALLOWED_ARCHIVE_HOSTS = {
    "github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
# Local state that must survive an update. Top-level names only.
PRESERVE_TOP = frozenset(
    {
        "data",
        "media",
        ".env",
        ".venv",
        "venv",
        "staticfiles",
        ".git",
        ".cursor",
        ".idea",
        ".vscode",
        "__pycache__",
        ".pytest_cache",
    }
)
SKIP_NAMES = frozenset({"__pycache__", ".git", ".pytest_cache"})

INSTALL_STEPS = [
    ("prepare", "Prepare"),
    ("download", "Download"),
    ("apply", "Apply"),
    ("deps", "Dependencies"),
    ("migrate", "Migrate"),
    ("collectstatic", "Collect static"),
    ("restart", "Restart"),
]


def _parse_version(value):
    """Return a comparable tuple for a semver-ish string, or None."""
    if not value:
        return None
    cleaned = value.strip().lstrip("vV")
    parts = cleaned.split(".")
    numbers = []
    for part in parts:
        match = re.match(r"^(\d+)", part)
        if not match:
            return None
        numbers.append(int(match.group(1)))
    if not numbers:
        return None
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)


def is_newer(latest, current):
    latest_parsed = _parse_version(latest)
    current_parsed = _parse_version(current)
    if latest_parsed is None or current_parsed is None:
        return bool(latest) and latest.strip().lstrip("vV") != (current or "").strip().lstrip("vV")
    return latest_parsed > current_parsed


def _same_version(left, right):
    a = (left or "").strip().lstrip("vV")
    b = (right or "").strip().lstrip("vV")
    return bool(a) and a == b


def _parse_published_at(value):
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=dt_timezone.utc)


def _github_json(url, headers):
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    return resp, payload


def _newest_release(releases):
    candidates = [
        row
        for row in releases
        if isinstance(row, dict)
        and not row.get("draft")
        and (row.get("tag_name") or "").strip()
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: _parse_version(row.get("tag_name")) or (0, 0, 0),
    )


def _github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "control-center-updater",
    }
    token = getattr(settings, "GITHUB_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_latest_release(repo):
    """Return (payload, error). Includes prereleases; /releases/latest ignores them."""
    headers = _github_headers()
    list_url = f"{GITHUB_API_ROOT}/repos/{repo}/releases?per_page=30"
    try:
        resp, payload = _github_json(list_url, headers)
    except requests.RequestException as exc:
        logger.warning("Update check failed: %s", exc)
        return None, str(exc)[:255]

    if resp.status_code == 404:
        return None, NO_RELEASES_MESSAGE
    if not resp.ok:
        return None, f"GitHub returned {resp.status_code}"
    if not isinstance(payload, list):
        return None, "Malformed response from GitHub"

    newest = _newest_release(payload)
    if newest:
        return newest, ""
    return None, NO_RELEASES_MESSAGE


def check_for_update():
    """Fetch the latest release from GitHub and persist the result."""
    status = UpdateStatus.load()
    repo = settings.GITHUB_REPO
    if not repo:
        status.check_error = "No GitHub repository configured."
        status.last_checked_at = timezone.now()
        status.save()
        return status

    payload, error = _fetch_latest_release(repo)
    if error or not payload:
        status.check_error = error or NO_RELEASES_MESSAGE
        status.latest_version = ""
        status.release_url = ""
        status.release_notes = ""
        status.release_published_at = None
        status.last_checked_at = timezone.now()
        status.save()
        return status

    status.latest_version = (payload.get("tag_name") or "").strip()[:32]
    status.release_url = payload.get("html_url") or ""
    status.release_notes = (payload.get("body") or "").strip()
    status.release_published_at = _parse_published_at(payload.get("published_at"))
    status.check_error = ""
    status.last_checked_at = timezone.now()
    status.save()

    if is_newer(status.latest_version, get_current_version()):
        logger.info(
            "Update available: %s (current %s)",
            status.latest_version,
            get_current_version(),
        )
    return clear_stale_install_progress(status)


def maybe_check_for_update(force=False):
    """Check at most once per UPDATE_CHECK_INTERVAL_HOURS unless forced."""
    status = UpdateStatus.load()
    if not force and status.last_checked_at:
        age = timezone.now() - status.last_checked_at
        if age.total_seconds() < settings.UPDATE_CHECK_INTERVAL_HOURS * 3600:
            return clear_stale_install_progress(status)
    if not cache.add(CHECK_LOCK_KEY, "1", CHECK_LOCK_TTL):
        return clear_stale_install_progress(status)
    try:
        return check_for_update()
    finally:
        cache.delete(CHECK_LOCK_KEY)


def update_available(status=None):
    status = status or UpdateStatus.load()
    return is_newer(status.latest_version, get_current_version())


def clear_stale_install_progress(status=None):
    """Drop leftover SUCCESS/FAILED UI when a newer release is available.

    After a successful install the row stays SUCCESS with the old log. When a
    later GitHub release appears, that leftover would hide Install and show
    100% complete for the previous update.
    """
    status = status or UpdateStatus.load()
    if status.install_state not in (
        UpdateStatus.InstallState.SUCCESS,
        UpdateStatus.InstallState.FAILED,
    ):
        return status
    if not update_available(status):
        return status
    last = (status.installed_version or status.install_target_version or "").strip()
    latest = (status.latest_version or "").strip()
    if last and _same_version(last, latest):
        return status
    status.install_state = UpdateStatus.InstallState.IDLE
    status.install_log = ""
    status.install_step = ""
    status.install_step_index = 0
    status.install_finished_at = None
    status.restart_required = False
    status.install_target_version = ""
    status.save()
    return status


def _lock_path():
    return Path(settings.BASE_DIR) / "data" / "update-install.lock"


def _pid_is_running(pid):
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _lock_pid():
    path = _lock_path()
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def acquire_install_lock(pid=None):
    """Record the update process pid. Replaces a stale lock from a dead pid."""
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = _lock_pid()
    if current and _pid_is_running(current) and current != (pid or os.getpid()):
        return False
    path.write_text(str(pid or os.getpid()), encoding="utf-8")
    return True


def release_install_lock():
    path = _lock_path()
    try:
        stored = _lock_pid()
        if stored in (None, os.getpid()):
            path.unlink(missing_ok=True)
    except OSError:
        pass


def recover_stale_install():
    """Mark a RUNNING install failed when the worker process is gone."""
    status = UpdateStatus.load()
    if status.install_state != UpdateStatus.InstallState.RUNNING:
        return False
    pid = _lock_pid()
    if _pid_is_running(pid):
        return False
    if pid is None and status.install_started_at:
        age = (timezone.now() - status.install_started_at).total_seconds()
        if age < STALE_INSTALL_GRACE_SECONDS:
            return False
    log = [status.install_log.strip(), "Update process stopped before it finished."]
    _finish(status, UpdateStatus.InstallState.FAILED, [line for line in log if line])
    try:
        _lock_path().unlink(missing_ok=True)
    except OSError:
        pass
    logger.warning("Cleared a stale in-app update")
    return True


def app_dir_is_ephemeral(app_dir=None, *, in_docker=None, mountinfo=None):
    """True in Docker when the app directory is not bind-mounted from the host."""
    if in_docker is None:
        in_docker = Path("/.dockerenv").exists()
    if not in_docker:
        return False
    app = str(Path(app_dir or settings.BASE_DIR).resolve())
    if mountinfo is None:
        try:
            mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        except OSError:
            return True
    for line in mountinfo.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        if parts[4] == app:
            return False
    return True


def _progress(status, log, index, label):
    """Persist live progress so the UI can poll between steps."""
    if status is None:
        return
    status.install_step = label
    status.install_step_index = index
    status.install_total_steps = len(INSTALL_STEPS)
    status.install_log = "\n".join(log)[-20000:]
    status.save(
        update_fields=[
            "install_step",
            "install_step_index",
            "install_total_steps",
            "install_log",
        ]
    )


def _run_step(label, args, log, cwd, timeout=900, status=None, step_index=None):
    """Run a command and stream stdout/stderr into the install log."""
    log.append(f"$ {' '.join(args)}")
    _progress(status, log, step_index if step_index is not None else 0, label)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    try:
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
    except OSError as exc:
        log.append(f"{label} could not start: {exc}")
        return False

    deadline = time.monotonic() + timeout
    started = time.monotonic()
    last_output = started
    last_flush = started
    try:
        while True:
            now = time.monotonic()
            if now > deadline:
                proc.kill()
                proc.wait(timeout=10)
                log.append(f"{label} timed out after {timeout}s")
                return False
            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if ready:
                chunk = proc.stdout.readline()
                if chunk:
                    log.append(chunk.decode("utf-8", errors="replace").rstrip())
                    last_output = now
                elif proc.poll() is not None:
                    leftover = proc.stdout.read()
                    if leftover:
                        text = leftover.decode("utf-8", errors="replace").rstrip()
                        if text:
                            log.append(text)
                    break
            elif proc.poll() is not None:
                leftover = proc.stdout.read()
                if leftover:
                    text = leftover.decode("utf-8", errors="replace").rstrip()
                    if text:
                        log.append(text)
                break
            elif now - last_output >= LOCK_HEARTBEAT_SECONDS:
                log.append(f"{label} still running ({int(now - started)}s)…")
                last_output = now
            if status is not None and now - last_flush >= 1:
                _progress(status, log, step_index if step_index is not None else 0, label)
                last_flush = now
        proc.wait(timeout=10)
    except Exception as exc:  # noqa: BLE001 - surface in the install log
        log.append(f"{label} stopped: {exc}")
        if proc.poll() is None:
            proc.kill()
        return False
    if proc.returncode != 0:
        log.append(f"{label} failed with exit code {proc.returncode}")
        return False
    return True


def _finish(status, state, log, installed_version="", restart_required=False):
    status.install_state = state
    status.install_log = "\n".join(log)[-20000:]
    status.install_finished_at = timezone.now()
    status.restart_required = restart_required
    if state == UpdateStatus.InstallState.SUCCESS:
        status.install_step_index = len(INSTALL_STEPS)
        status.install_step = "done"
    if installed_version:
        status.installed_version = installed_version
    status.save()
    return status


def _command_available(command):
    args = shlex.split(command)
    return bool(args) and shutil.which(args[0]) is not None


def _under_gunicorn():
    return any("gunicorn" in arg for arg in sys.argv)


def _find_gunicorn_master():
    """Return the gunicorn master pid, including when we are a sidecar process."""
    if _under_gunicorn():
        return os.getppid()
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None
    candidates = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes().replace(b"\x00", b" ")
            cmdline = raw.decode("utf-8", errors="replace").strip()
        except OSError:
            continue
        lower = cmdline.lower()
        if "gunicorn" not in lower:
            continue
        if "install_update" in lower or "manage.py" in lower:
            continue
        if "gunicorn: worker" in lower:
            continue
        candidates.append(int(entry.name))
    if not candidates:
        return None
    return min(candidates)


def _restart_application(log):
    """Reload the server. Prefer a configured host command, then gunicorn SIGHUP."""
    command = settings.UPDATE_RESTART_COMMAND.strip()
    if command and not _command_available(command):
        log.append(
            f"UPDATE_RESTART_COMMAND ({command}) is not available here; "
            "falling back to a graceful reload."
        )
        command = ""
    if command:
        args = shlex.split(command)
        log.append(f"$ {' '.join(args)}")
        try:
            subprocess.Popen(
                args,
                cwd=str(settings.BASE_DIR),
                start_new_session=True,
            )
            return True
        except OSError as exc:
            log.append(f"Restart command failed: {exc}")
            return False

    master = _find_gunicorn_master()
    if master:
        log.append(f"Sending SIGHUP to gunicorn master (pid {master})")
        try:
            os.kill(master, signal.SIGHUP)
            return True
        except OSError as exc:
            log.append(f"Could not signal gunicorn master: {exc}")
            return False

    log.append("No restart command configured — restart the service manually.")
    return False


def archive_url(repo, tag):
    if not REPO_PATTERN.match(repo or ""):
        raise ValueError("Invalid GitHub repository.")
    if not TAG_PATTERN.match(tag or ""):
        raise ValueError("Invalid release tag.")
    return f"https://github.com/{repo}/archive/refs/tags/{tag}.tar.gz"


def _host_allowed(url):
    host = (urlparse(url).hostname or "").lower()
    return host in ALLOWED_ARCHIVE_HOSTS


def download_archive(url, dest, log, timeout=DOWNLOAD_TIMEOUT):
    if not _host_allowed(url):
        raise ValueError(f"Refusing to download from {urlparse(url).hostname}")
    log.append(f"Downloading {url}")
    with requests.get(
        url,
        headers=_github_headers(),
        stream=True,
        timeout=timeout,
        allow_redirects=True,
    ) as resp:
        if not _host_allowed(resp.url):
            raise ValueError(f"Refusing redirect to {urlparse(resp.url).hostname}")
        if resp.status_code == 404:
            raise ValueError("Release archive not found. Publish a GitHub release for this tag.")
        resp.raise_for_status()
        written = 0
        with dest.open("wb") as handle:
            for chunk in resp.iter_content(DOWNLOAD_CHUNK):
                if not chunk:
                    continue
                handle.write(chunk)
                written += len(chunk)
    if written < 32:
        raise ValueError("Downloaded archive is empty.")
    log.append(f"Downloaded {written} bytes")
    return written


def _safe_tar_members(tar, dest):
    dest = dest.resolve()
    members = []
    for member in tar.getmembers():
        if member.name.startswith("/") or member.name.startswith("\\"):
            raise ValueError(f"Unsafe path in archive: {member.name}")
        target = (dest / member.name).resolve()
        if target != dest and not str(target).startswith(str(dest) + os.sep):
            raise ValueError(f"Unsafe path in archive: {member.name}")
        if member.issym() or member.islnk():
            continue
        members.append(member)
    return members


def extract_release_tarball(archive_path, dest):
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(dest, members=_safe_tar_members(tar, dest), filter="data")
    roots = [p for p in dest.iterdir() if p.is_dir()]
    if len(roots) == 1:
        return roots[0]
    raise ValueError("Release archive did not contain a single project folder.")


def _sync_tree(src, dest):
    dest.mkdir(parents=True, exist_ok=True)
    incoming = {child.name for child in src.iterdir() if child.name not in SKIP_NAMES}
    for child in list(dest.iterdir()):
        if child.name in SKIP_NAMES or child.name in PRESERVE_TOP:
            continue
        if child.name not in incoming:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    for child in src.iterdir():
        if child.name in SKIP_NAMES:
            continue
        target = dest / child.name
        if child.is_dir():
            _sync_tree(child, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def apply_release_tree(src_root, dest_root, log):
    """Replace app files from a release tree. Local state directories are kept."""
    copied = 0
    for child in src_root.iterdir():
        if child.name in PRESERVE_TOP or child.name in SKIP_NAMES:
            continue
        target = dest_root / child.name
        if child.is_dir():
            _sync_tree(child, target)
            copied += 1
        else:
            shutil.copy2(child, target)
            copied += 1
    log.append(f"Applied {copied} top-level items from the release")
    return copied


def verify_installed_version(dest_root, target_tag):
    version_file = dest_root / "VERSION"
    if not version_file.is_file():
        raise ValueError("Release is missing a VERSION file.")
    actual = version_file.read_text(encoding="utf-8").strip()
    expected = target_tag.strip().lstrip("vV")
    if actual != expected:
        raise ValueError(f"VERSION is {actual}, expected {expected}.")
    return actual


def _fail_install(status, log, target_tag, username, label):
    _finish(status, UpdateStatus.InstallState.FAILED, log)
    log_audit(
        "admin",
        message=f"Update to {target_tag} failed at {label.lower()}",
        username=username,
    )
    _notify(f"Update to {target_tag} failed", label)


def run_install(target_tag, username=""):
    """Apply a release. Called from `manage.py install_update`, not the web worker."""
    dest_root = Path(settings.BASE_DIR)
    base_dir = str(dest_root)
    acquire_install_lock()
    status = UpdateStatus.load()
    log = [
        f"Updating to {target_tag} (current {get_current_version()})",
        f"Update process pid {os.getpid()}",
    ]
    if app_dir_is_ephemeral(dest_root):
        log.append(
            "App directory is not bind-mounted. This update lasts until the "
            "container is recreated. Rebuild the image for a durable Docker upgrade."
        )
    status.install_total_steps = len(INSTALL_STEPS)
    status.save(update_fields=["install_total_steps"])

    try:
        _progress(status, log, 1, "Prepare")
        repo = settings.GITHUB_REPO
        if not REPO_PATTERN.match(repo or ""):
            log.append("GITHUB_REPO is not a valid owner/name value.")
            _fail_install(status, log, target_tag, username, "Prepare")
            return
        try:
            url = archive_url(repo, target_tag)
        except ValueError as exc:
            log.append(str(exc))
            _fail_install(status, log, target_tag, username, "Prepare")
            return

        with tempfile.TemporaryDirectory(prefix="cc-update-") as tmp:
            tmp_path = Path(tmp)
            archive_path = tmp_path / "release.tar.gz"
            extract_dir = tmp_path / "src"

            _progress(status, log, 2, "Download")
            try:
                download_archive(url, archive_path, log)
            except Exception as exc:  # noqa: BLE001 - surface download errors in the log
                log.append(f"Download failed: {exc}")
                _fail_install(status, log, target_tag, username, "Download")
                return

            _progress(status, log, 3, "Apply")
            try:
                src_root = extract_release_tarball(archive_path, extract_dir)
                apply_release_tree(src_root, dest_root, log)
                installed = verify_installed_version(dest_root, target_tag)
                log.append(f"Release tree is {installed}")
            except Exception as exc:  # noqa: BLE001 - surface apply errors in the log
                log.append(f"Apply failed: {exc}")
                _fail_install(status, log, target_tag, username, "Apply")
                return

        command_steps = [
            (
                4,
                "Dependencies",
                [sys.executable, "-u", "-m", "pip", "install", "-r", "requirements.txt"],
                1800,
            ),
            (5, "Migrate", [sys.executable, "manage.py", "migrate", "--noinput"], 600),
            (
                6,
                "Collect static",
                [sys.executable, "manage.py", "collectstatic", "--noinput"],
                600,
            ),
        ]
        for index, label, args, timeout in command_steps:
            _progress(status, log, index, label)
            if not _run_step(
                label, args, log, base_dir, timeout, status=status, step_index=index
            ):
                _fail_install(status, log, target_tag, username, label)
                return
            _progress(status, log, index, label)

        _progress(status, log, 7, "Restart")
        clear_version_cache()
        new_version = get_current_version()
        log.append(f"Updated to {new_version}")
        log.append("Saving status, then reloading the app…")
        _finish(
            status,
            UpdateStatus.InstallState.SUCCESS,
            log,
            installed_version=new_version,
            restart_required=False,
        )
        log_audit(
            "admin",
            message=f"Installed update {target_tag}",
            username=username,
        )
        restarted = _restart_application(log)
        status = UpdateStatus.load()
        status.restart_required = not restarted
        status.install_log = "\n".join(log)[-20000:]
        status.save(update_fields=["restart_required", "install_log"])
        _notify(f"Control Center updated to {new_version}", "Update installed")
    except Exception as exc:  # noqa: BLE001 - background process must not die silently
        logger.exception("Update install crashed")
        log.append(f"Unexpected error: {exc}")
        _finish(status, UpdateStatus.InstallState.FAILED, log)
    finally:
        release_install_lock()
        cache.delete(INSTALL_LOCK_KEY)


def _notify(title, message):
    try:
        from dashboard.services import send_ntfy

        send_ntfy(title, message)
    except Exception as exc:  # noqa: BLE001 - notification is best effort
        logger.debug("Update notification failed: %s", exc)


def start_install(target_tag, username=""):
    """Queue an update in a detached process so gunicorn can keep serving.

    Returns ``(started, message)``.
    """
    recover_stale_install()
    if not settings.UPDATES_ALLOW_INSTALL:
        return False, "In-app updates are disabled."
    if not target_tag or not TAG_PATTERN.match(target_tag):
        return False, "Invalid release tag."
    if not cache.add(INSTALL_LOCK_KEY, "1", INSTALL_LOCK_TTL):
        return False, "An update is already running."

    status = UpdateStatus.load()
    if status.install_state == UpdateStatus.InstallState.RUNNING:
        cache.delete(INSTALL_LOCK_KEY)
        return False, "An update is already running."
    if _pid_is_running(_lock_pid()):
        cache.delete(INSTALL_LOCK_KEY)
        return False, "An update is already running."

    status.install_state = UpdateStatus.InstallState.RUNNING
    status.install_started_at = timezone.now()
    status.install_finished_at = None
    status.install_log = f"Queued update to {target_tag}…"
    status.restart_required = False
    status.install_step = "Prepare"
    status.install_step_index = 0
    status.install_total_steps = len(INSTALL_STEPS)
    status.install_target_version = target_tag[:32]
    status.save()

    manage = Path(settings.BASE_DIR) / "manage.py"
    args = [sys.executable, str(manage), "install_update", target_tag, "--username", username or ""]
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(settings.BASE_DIR),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except OSError as exc:
        cache.delete(INSTALL_LOCK_KEY)
        log = [status.install_log, f"Could not start update process: {exc}"]
        _finish(status, UpdateStatus.InstallState.FAILED, log)
        return False, f"Could not start update process: {exc}"
    acquire_install_lock(pid=proc.pid)
    return True, f"Installing {target_tag}."


def status_payload(status=None):
    recovered = recover_stale_install()
    if status is None or recovered:
        status = UpdateStatus.load()
    status = clear_stale_install_progress(status)
    current = get_current_version()
    total = status.install_total_steps or len(INSTALL_STEPS)
    index = status.install_step_index or 0
    if status.install_state == UpdateStatus.InstallState.SUCCESS:
        percent = 100
    elif status.install_state == UpdateStatus.InstallState.IDLE:
        percent = 0
    elif total:
        percent = min(99, round(index / total * 100))
    else:
        percent = 0
    return {
        "current_version": current,
        "latest_version": status.latest_version,
        "update_available": update_available(status),
        "release_url": status.release_url,
        "release_notes": status.release_notes,
        "release_published_at": (
            status.release_published_at.isoformat()
            if status.release_published_at
            else None
        ),
        "last_checked_at": (
            status.last_checked_at.isoformat() if status.last_checked_at else None
        ),
        "check_error": status.check_error,
        "install_state": status.install_state,
        "install_log": status.install_log,
        "installed_version": status.installed_version,
        "restart_required": status.restart_required,
        "install_allowed": settings.UPDATES_ALLOW_INSTALL,
        "install_step": status.install_step,
        "install_step_index": index,
        "install_total_steps": total,
        "install_target_version": status.install_target_version,
        "install_started_at": (
            status.install_started_at.isoformat() if status.install_started_at else None
        ),
        "install_steps": [{"id": sid, "label": label} for sid, label in INSTALL_STEPS],
        "install_percent": percent,
    }
