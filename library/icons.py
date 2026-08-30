"""Resolve app icons consistently across Library and dashboard."""

import json
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings
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
    "filebrowser": "files",
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


@lru_cache(maxsize=1)
def all_simpleicons():
    path = Path(settings.BASE_DIR) / "static" / "data" / "simpleicons.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def default_icon_url():
    return static("img/service-default.svg")


def simpleicons_slug(slug):
    return _SIMPLEICONS_ALIASES.get(slug, (slug or "").replace("-", ""))


def library_icon_url(slug):
    return f"{_SIMPLEICONS}{slug}/E87722"


def lookup_simpleicons_slug(slug="", name=""):
    """Return a simpleicons slug from the bundled list, or empty if none match."""
    icons = all_simpleicons()
    if not icons:
        return ""
    by_slug = {row["slug"].lower(): row["slug"] for row in icons}
    candidates = []
    if slug:
        alias = _SIMPLEICONS_ALIASES.get(slug, "")
        if alias:
            candidates.append(alias)
        compact = re.sub(r"[^a-z0-9]", "", slug.lower())
        candidates.extend((slug.lower(), compact, slug.replace("-", "").lower()))
    if name:
        compact = re.sub(r"[^a-z0-9]", "", name.lower())
        candidates.append(compact)
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if candidate in by_slug:
            return by_slug[candidate]
    if name:
        needle = name.strip().lower()
        for row in icons:
            if row["title"].lower() == needle:
                return row["slug"]
    return ""


def icon_url_for_entry(slug, icon_field="", name=""):
    """Prefer the bundled icon list; fall back to the catalog's original icon."""
    matched = lookup_simpleicons_slug(slug, name=name)
    if matched:
        return library_icon_url(matched)
    if icon_field and str(icon_field).startswith(("http://", "https://", "/")):
        return icon_field
    return default_icon_url()


def icon_url_for_slug(slug):
    if not slug:
        return default_icon_url()
    svc = get_service_by_slug(slug)
    if svc:
        return icon_url_for_entry(slug, svc.get("icon", ""), name=svc.get("name", ""))
    for addon in ADDONS:
        if addon["slug"] == slug:
            return icon_url_for_entry(slug, addon.get("icon", ""), name=addon.get("name", ""))
    matched = lookup_simpleicons_slug(slug)
    if matched:
        return library_icon_url(matched)
    return default_icon_url()
