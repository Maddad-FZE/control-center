"""Template loaders that prefer the active theme pack, then its parents."""

from django.template.loaders.cached import Loader as CachedLoader
from django.template.loaders.filesystem import Loader as FilesystemLoader

from core.themes.middleware import get_active_theme


class ThemeLoader(FilesystemLoader):
    """Look in each pack's templates/ dir, child before parent."""

    def get_dirs(self):
        theme = get_active_theme()
        dirs = []
        for pack in theme.chain:
            folder = pack.templates_dir
            if folder.is_dir() and not folder.is_symlink():
                dirs.append(folder)
        return dirs


class ThemeCachedLoader(CachedLoader):
    """Cached loader whose key includes the theme slug."""

    def cache_key(self, template_name, skip=None):
        theme = get_active_theme()
        slug = theme.slug if theme else ""
        return f"{slug}-{super().cache_key(template_name, skip)}"


def configured_loaders(debug):
    inner = [
        "core.themes.loaders.ThemeLoader",
        "django.template.loaders.filesystem.Loader",
        "django.template.loaders.app_directories.Loader",
    ]
    if debug:
        return inner
    return [("core.themes.loaders.ThemeCachedLoader", inner)]
