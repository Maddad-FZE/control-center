from django import template
from django.conf import settings
from django.templatetags.static import static

from core.themes.middleware import get_active_theme
from core.version import get_asset_token

register = template.Library()


@register.simple_tag
def vstatic(path):
    try:
        url = static(path)
    except ValueError:
        base = (settings.STATIC_URL or "/static/").rstrip("/")
        url = f"{base}/{str(path).lstrip('/')}"
    version = get_asset_token()
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={version}"


@register.simple_tag
def theme_static(path):
    """URL for a static file in the active pack or the nearest parent."""
    theme = get_active_theme()
    rel = str(path or "").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return ""
    for pack in theme.chain:
        candidate = pack.static_dir / rel
        if candidate.is_file() and not candidate.is_symlink():
            return vstatic(f"themes/{pack.slug}/{rel}")
    return ""
