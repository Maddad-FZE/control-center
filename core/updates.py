"""Version checking against GitHub Releases and in-place archive installs."""

import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
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
INSTALL_LOCK_TTL = 1800
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
    return status


def maybe_check_for_update(force=False):
    """Check at most once per UPDATE_CHECK_INTERVAL_HOURS unless forced."""
    status = UpdateStatus.load()
    if not force and status.last_checked_at:
        age = timezone.now() - status.last_checked_at
        if age.total_seconds() < settings.UPDATE_CHECK_INTERVAL_HOURS * 3600:
            return status
    if not cache.add(CHECK_LOCK_KEY, "1", CHECK_LOCK_TTL):
        return status
    try:
        return check_for_update()
    finally:
        cache.delete(CHECK_LOCK_KEY)


def update_available(status=None):
    status = status or UpdateStatus.load()
    return is_newer(status.latest_version, get_current_version())


def _progress(status, log, index, label):
    """Persist live progress so the UI can poll between steps."""
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


def _run_step(label, args, log, cwd, timeout=900):
    log.append(f"$ {' '.join(args)}")
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log.append(f"{label} timed out after {timeout}s")
        return False
    except OSError as exc:
        log.append(f"{label} could not start: {exc}")
        return False
    output = (result.stdout or "") + (result.stderr or "")
    if output.strip():
        log.append(output.strip())
    if result.returncode != 0:
        log.append(f"{label} failed with exit code {result.returncode}")
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


def _restart_application(log):
    """Restart the server so the new code is loaded."""
    command = settings.UPDATE_RESTART_COMMAND.strip()
    if not command and Path("/.dockerenv").exists():
        command = "docker restart control-center"
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

    if "gunicorn" in os.environ.get("SERVER_SOFTWARE", "").lower() or _under_gunicorn():
        parent = os.getppid()
        log.append(f"Sending SIGHUP to gunicorn master (pid {parent})")
        try:
            os.kill(parent, signal.SIGHUP)
            return True
        except OSError as exc:
            log.append(f"Could not signal gunicorn master: {exc}")
            return False

    log.append("No restart command configured — restart the service manually.")
    return False


def _under_gunicorn():
    return any("gunicorn" in arg for arg in sys.argv)


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


def _install_worker(target_tag, username):
    dest_root = Path(settings.BASE_DIR)
    base_dir = str(dest_root)
    status = UpdateStatus.load()
    log = [f"Updating to {target_tag} (current {get_current_version()})"]
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
                [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
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
            if not _run_step(label, args, log, base_dir, timeout):
                _fail_install(status, log, target_tag, username, label)
                return
            _progress(status, log, index, label)

        _progress(status, log, 7, "Restart")
        clear_version_cache()
        new_version = get_current_version()
        log.append(f"Updated to {new_version}")
        restarted = _restart_application(log)
        _finish(
            status,
            UpdateStatus.InstallState.SUCCESS,
            log,
            installed_version=new_version,
            restart_required=not restarted,
        )
        log_audit(
            "admin",
            message=f"Installed update {target_tag}",
            username=username,
        )
        _notify(f"Control Center updated to {new_version}", "Update installed")
    except Exception as exc:  # noqa: BLE001 - background thread must not die silently
        logger.exception("Update install crashed")
        log.append(f"Unexpected error: {exc}")
        _finish(status, UpdateStatus.InstallState.FAILED, log)
    finally:
        cache.delete(INSTALL_LOCK_KEY)


def _notify(title, message):
    try:
        from dashboard.services import send_ntfy

        send_ntfy(title, message)
    except Exception as exc:  # noqa: BLE001 - notification is best effort
        logger.debug("Update notification failed: %s", exc)


def start_install(target_tag, username=""):
    """Kick off an update install in the background.

    Returns ``(started, message)``.
    """
    if not settings.UPDATES_ALLOW_INSTALL:
        return False, "In-app updates are disabled."
    if not target_tag or not TAG_PATTERN.match(target_tag):
        return False, "Invalid release tag."
    if not cache.add(INSTALL_LOCK_KEY, "1", INSTALL_LOCK_TTL):
        return False, "An update is already running."

    status = UpdateStatus.load()
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

    thread = threading.Thread(
        target=_install_worker,
        args=(target_tag, username),
        name="update-install",
        daemon=True,
    )
    thread.start()
    return True, f"Installing {target_tag}."


def status_payload(status=None):
    status = status or UpdateStatus.load()
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
