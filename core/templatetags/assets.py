from django import template
from django.conf import settings
from django.templatetags.static import static

from core.version import get_asset_token

register = template.Library()


@register.simple_tag
def vstatic(path):
    url = static(path)
    version = get_asset_token()
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={version}"
