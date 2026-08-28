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


def clear_version_cache():
    get_current_version.cache_clear()
    get_git_revision.cache_clear()
