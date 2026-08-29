"""Version checking against GitHub Releases and in-place git updates."""

import logging
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

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
NO_RELEASES_MESSAGE = "No releases published yet."

INSTALL_STEPS = [
    ("prepare", "Prepare"),
    ("fetch", "Fetch"),
    ("checkout", "Checkout"),
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


def check_for_update():
    """Fetch the latest release from GitHub and persist the result."""
    status = UpdateStatus.load()
    repo = settings.GITHUB_REPO
    if not repo:
        status.check_error = "No GitHub repository configured."
        status.last_checked_at = timezone.now()
        status.save()
        return status

    url = f"{GITHUB_API_ROOT}/repos/{repo}/releases/latest"
    headers = {"Accept": "application/vnd.github+json"}
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("Update check failed: %s", exc)
        status.check_error = str(exc)[:255]
        status.last_checked_at = timezone.now()
        status.save()
        return status

    if resp.status_code == 404:
        status.check_error = NO_RELEASES_MESSAGE
        status.latest_version = ""
        status.release_url = ""
        status.release_notes = ""
        status.release_published_at = None
        status.last_checked_at = timezone.now()
        status.save()
        return status

    if not resp.ok:
        status.check_error = f"GitHub returned {resp.status_code}"
        status.last_checked_at = timezone.now()
        status.save()
        return status

    try:
        payload = resp.json()
    except ValueError:
        status.check_error = "Malformed response from GitHub"
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


def _install_worker(target_tag, username):
    base_dir = str(settings.BASE_DIR)
    status = UpdateStatus.load()
    log = [f"Updating to {target_tag} (current {get_current_version()})"]
    status.install_total_steps = len(INSTALL_STEPS)
    status.save(update_fields=["install_total_steps"])

    try:
        _progress(status, log, 1, "Prepare")
        if not (settings.BASE_DIR / ".git").exists():
            log.append("Not a git checkout — in-place updates are unavailable.")
            _finish(status, UpdateStatus.InstallState.FAILED, log)
            return

        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if dirty.returncode != 0:
            log.append("Could not read git status; aborting.")
            _finish(status, UpdateStatus.InstallState.FAILED, log)
            return
        if dirty.stdout.strip():
            log.append(
                "Working tree has uncommitted changes. Commit or stash them "
                "before installing an update."
            )
            _finish(status, UpdateStatus.InstallState.FAILED, log)
            return

        command_steps = [
            (2, "Fetch", ["git", "fetch", "--tags", "--prune", "origin"], 300),
            (3, "Checkout", ["git", "checkout", target_tag], 300),
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
                _finish(status, UpdateStatus.InstallState.FAILED, log)
                log_audit(
                    "admin",
                    message=f"Update to {target_tag} failed at {label.lower()}",
                    username=username,
                )
                _notify(f"Update to {target_tag} failed", label)
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
