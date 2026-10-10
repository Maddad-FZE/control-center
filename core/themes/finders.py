"""Serve pack static files at themes/<slug>/… via collectstatic."""

from pathlib import Path

from django.contrib.staticfiles.finders import BaseFinder
from django.contrib.staticfiles.utils import get_files
from django.core.files.storage import FileSystemStorage

from core.themes.registry import get_packs


class ThemeFinder(BaseFinder):
    def __init__(self, app_names=None, *args, **kwargs):
        self.storages = {}
        for pack in get_packs().values():
            static_dir = pack.static_dir
            if not static_dir.is_dir() or static_dir.is_symlink():
                continue
            prefix = f"themes/{pack.slug}"
            storage = FileSystemStorage(location=str(static_dir.resolve()))
            storage.prefix = prefix
            self.storages[prefix] = storage

    def find(self, path, all=False):
        matches = []
        for prefix, storage in self.storages.items():
            marker = prefix + "/"
            if not path.startswith(marker):
                continue
            rel = path[len(marker):]
            if not rel or ".." in Path(rel).parts:
                continue
            target = Path(storage.path(rel))
            root = Path(storage.location)
            try:
                target.resolve().relative_to(root)
            except (ValueError, OSError):
                continue
            if target.is_symlink() or not target.is_file():
                continue
            if not all:
                return str(target)
            matches.append(str(target))
        return matches

    def list(self, ignore_patterns):
        for prefix, storage in self.storages.items():
            if not os_path_ok(storage.location):
                continue
            for path in get_files(storage, ignore_patterns):
                yield path, storage


def os_path_ok(location):
    path = Path(location)
    return path.is_dir() and not path.is_symlink()
