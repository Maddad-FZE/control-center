from .catalog import ADDONS
from .models import AddonState


def _disabled_slugs():
    return set(AddonState.objects.filter(enabled=False).values_list("slug", flat=True))


def is_addon_enabled(slug):
    if slug not in {a["slug"] for a in ADDONS}:
        return True
    state = AddonState.objects.filter(slug=slug).first()
    if state is None:
        return True
    return state.enabled


def get_addon_by_slug(slug):
    for addon in ADDONS:
        if addon["slug"] == slug:
            return addon
    return None


def get_enabled_addon_nav_entries():
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
    return entries


def addon_states_for_catalog():
    disabled = _disabled_slugs()
    states = {}
    for addon in ADDONS:
        states[addon["slug"]] = addon["slug"] not in disabled
    return states


def set_addon_enabled(slug, enabled):
    AddonState.objects.update_or_create(slug=slug, defaults={"enabled": enabled})
