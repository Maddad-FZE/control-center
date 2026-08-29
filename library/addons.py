from django.core.cache import cache

from .catalog import ADDONS
from .models import AddonState

ADDON_DISABLED_CACHE_KEY = "addon:disabled_slugs"
ADDON_NAV_CACHE_KEY = "addon:nav_entries"


def clear_addon_cache():
    cache.delete(ADDON_DISABLED_CACHE_KEY)
    cache.delete(ADDON_NAV_CACHE_KEY)


def _disabled_slugs():
    cached = cache.get(ADDON_DISABLED_CACHE_KEY)
    if cached is not None:
        return cached
    slugs = set(AddonState.objects.filter(enabled=False).values_list("slug", flat=True))
    cache.set(ADDON_DISABLED_CACHE_KEY, slugs, 300)
    return slugs


def is_addon_enabled(slug):
    if slug not in {a["slug"] for a in ADDONS}:
        return True
    return slug not in _disabled_slugs()


def get_addon_by_slug(slug):
    for addon in ADDONS:
        if addon["slug"] == slug:
            return addon
    return None


def get_enabled_addon_nav_entries():
    cached = cache.get(ADDON_NAV_CACHE_KEY)
    if cached is not None:
        return cached
    disabled = _disabled_slugs()
    entries = []
    for addon in ADDONS:
        if addon["slug"] in disabled:
            continue
        entries.append(
            {
                "name": addon["name"],
                "url_name": addon["url_name"],
                "icon": addon.get("icon", "addon"),
            }
        )
    cache.set(ADDON_NAV_CACHE_KEY, entries, 300)
    return entries


def addon_states_for_catalog():
    disabled = _disabled_slugs()
    states = {}
    for addon in ADDONS:
        states[addon["slug"]] = addon["slug"] not in disabled
    return states


def set_addon_enabled(slug, enabled):
    AddonState.objects.update_or_create(slug=slug, defaults={"enabled": enabled})
    clear_addon_cache()
