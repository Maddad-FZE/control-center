"""Resolve app icons consistently across Library and dashboard."""

from django.templatetags.static import static

from .catalog import ADDONS, get_service_by_slug

_SIMPLEICONS = "https://cdn.simpleicons.org/"

# Catalog slug → simpleicons.org slug when they differ
_SIMPLEICONS_ALIASES = {
    "home-assistant": "homeassistant",
    "adguard-home": "adguard",
    "nginx-proxy-manager": "nginx",
    "wireguard-easy": "wireguard",
    "paperless-ngx": "paperlessngx",
    "actual-budget": "actualbudget",
    "speedtest-tracker": "speedtest",
    "file-browser": "files",
    "beszel": "linux",
    "nodered": "nodered",
    "esphome": "esphome",
    "zigbee2mqtt": "zigbee",
    "mosquitto": "eclipsemosquitto",
    "dockge": "docker",
    "coolify": "coolify",
    "authentik": "authentik",
    "authelia": "authelia",
    "vaultwarden": "bitwarden",
    "gitea": "gitea",
    "n8n": "n8n",
    "mealie": "mealie",
    "nextcloud": "nextcloud",
    "notes": "evernote",
}


def default_icon_url():
    return static("img/service-default.svg")


def simpleicons_slug(slug):
    return _SIMPLEICONS_ALIASES.get(slug, slug.replace("-", ""))


def icon_url_for_entry(slug, icon_field=""):
    """Best icon URL for a catalog entry (HTTP icon, simpleicons, or default)."""
    if icon_field and str(icon_field).startswith("http"):
        return icon_field
    if slug:
        return f"{_SIMPLEICONS}{simpleicons_slug(slug)}"
    return default_icon_url()


def icon_url_for_slug(slug):
    if not slug:
        return default_icon_url()
    svc = get_service_by_slug(slug)
    if svc:
        return icon_url_for_entry(slug, svc.get("icon", ""))
    for addon in ADDONS:
        if addon["slug"] == slug:
            return icon_url_for_entry(slug, addon.get("icon", ""))
    return default_icon_url()
