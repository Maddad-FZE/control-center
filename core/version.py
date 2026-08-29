"""Application version helpers.

The ``VERSION`` file at the repository root is the single source of truth so
that a git checkout of a release tag also updates the reported version.
"""

import subprocess
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "VERSION"
FALLBACK_VERSION = "0.0.0"


@lru_cache(maxsize=1)
def get_current_version():
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return FALLBACK_VERSION
    return version or FALLBACK_VERSION


@lru_cache(maxsize=1)
def get_git_revision():
    if not (BASE_DIR / ".git").exists():
        return ""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_asset_token():
    """Cache-bust token for CSS/JS. In DEBUG, follow file mtimes so edits apply immediately."""
    version = get_current_version()
    from django.conf import settings

    if not settings.DEBUG:
        return version
    newest = 0
    for folder in (BASE_DIR / "static" / "css", BASE_DIR / "static" / "js"):
        if not folder.exists():
            continue
        for path in folder.iterdir():
            if path.is_file():
                newest = max(newest, int(path.stat().st_mtime))
    return f"{version}.{newest}" if newest else version


def clear_version_cache():
    get_current_version.cache_clear()
    get_git_revision.cache_clear()
