"""DB-backed library catalog: seed, refresh from GitHub, CRUD, and delete guards."""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import docker
import requests
from django.conf import settings
from django.db import transaction

from .installer import DOCKER_LABEL_SLUG, get_docker_client
from .models import CatalogItem, InstalledService

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
BUNDLED_CATALOG = Path(__file__).resolve().parent.parent / "catalog" / "apps.json"
CATALOG_SCHEMA = 1
CATALOG_MAX_BYTES = 2 * 1024 * 1024
CATALOG_HOST = "raw.githubusercontent.com"


def catalog_url():
    explicit = (getattr(settings, "CATALOG_URL", "") or "").strip()
    if explicit:
        return explicit
    return "https://raw.githubusercontent.com/Maddad-FZE/alef-app-catalog/main/apps.json"


def _normalized_app(raw, slug, index):
    try:
        container_port = int(raw.get("container_port") or 0)
    except (TypeError, ValueError):
        container_port = 0
    try:
        sort_order = int(raw.get("sort_order", index))
    except (TypeError, ValueError):
        sort_order = index
    return {
        "slug": slug,
        "name": (raw.get("name") or "").strip(),
        "tagline": (raw.get("tagline") or "").strip(),
        "description": (raw.get("description") or raw.get("tagline") or "").strip(),
        "category": (raw.get("category") or "").strip(),
        "repo": (raw.get("repo") or "").strip(),
        "website": (raw.get("website") or "").strip(),
        "icon": (raw.get("icon") or "").strip(),
        "default_port": int(raw.get("default_port") or 8080),
        "container_port": container_port,
        "path": (raw.get("path") or "/").strip() or "/",
        "widget_type": (raw.get("widget_type") or "none").strip() or "none",
        "compose": (raw.get("compose") or "").strip(),
        "install_options": (raw.get("install_options") or "").strip(),
        "is_builtin": True,
        "sort_order": sort_order,
    }


def parse_catalog_document(payload):
    """Return (apps, errors). A non-empty error list means the file must not be applied."""
    if not isinstance(payload, dict) or payload.get("schema") != CATALOG_SCHEMA:
        return [], ["Catalog schema must be 1."]
    raw_apps = payload.get("apps")
    if not isinstance(raw_apps, list) or not raw_apps:
        return [], ["Catalog apps list is empty."]
    apps = []
    errors = []
    seen = set()
    for index, raw in enumerate(raw_apps):
        if not isinstance(raw, dict):
            errors.append(f"App {index + 1} is not an object.")
            continue
        row_errors, slug = validate_catalog_payload(raw)
        if slug in seen:
            row_errors.append(f"Duplicate slug “{slug}”.")
        if slug:
            seen.add(slug)
        if row_errors:
            errors.extend(row_errors)
            continue
        apps.append(_normalized_app(raw, slug, index))
    if errors:
        return [], errors
    return apps, []


def load_bundled_apps():
    payload = json.loads(BUNDLED_CATALOG.read_text(encoding="utf-8"))
    apps, errors = parse_catalog_document(payload)
    if errors:
        raise ValueError(errors[0])
    return apps


def seed_builtin_catalog():
    if CatalogItem.objects.exists():
        return 0
    rows = [CatalogItem(**fields) for fields in load_bundled_apps()]
    CatalogItem.objects.bulk_create(rows)
    return len(rows)


def ensure_catalog_seeded():
    if not CatalogItem.objects.exists():
        seed_builtin_catalog()


def _host_ok(url):
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == CATALOG_HOST


def fetch_catalog(url=None):
    """Return (apps, error). Does not write the database."""
    url = (url or catalog_url()).strip()
    if not _host_ok(url):
        return None, "Catalog URL must be https on raw.githubusercontent.com."
    try:
        resp = requests.get(
            url,
            timeout=20,
            allow_redirects=True,
            headers={
                "Accept": "application/json",
                "User-Agent": "control-center-catalog",
            },
        )
    except requests.RequestException as exc:
        return None, str(exc)[:255]
    if not _host_ok(resp.url):
        return None, "Refusing a catalog redirect off raw.githubusercontent.com."
    if not resp.ok:
        return None, f"GitHub returned {resp.status_code}"
    if len(resp.content) > CATALOG_MAX_BYTES:
        return None, "Catalog file is too large."
    try:
        payload = resp.json()
    except ValueError:
        return None, "Catalog file is not JSON."
    apps, errors = parse_catalog_document(payload)
    if errors:
        return None, errors[0]
    return apps, ""


@transaction.atomic
def apply_catalog(apps):
    """Replace built-in apps from a validated list. Manual and installed rows stay."""
    incoming = {row["slug"]: row for row in apps}
    existing = {item.slug: item for item in CatalogItem.objects.all()}
    installed = set(
        InstalledService.objects.filter(
            status__in=("running", "stopped", "installing")
        ).values_list("slug", flat=True)
    )
    added = updated = removed = kept_manual = kept_installed = 0
    for slug, fields in incoming.items():
        current = existing.get(slug)
        if current is not None and not current.is_builtin:
            kept_manual += 1
            continue
        if current is None:
            CatalogItem.objects.create(**fields)
            added += 1
            continue
        for key, value in fields.items():
            setattr(current, key, value)
        current.save()
        updated += 1
    for slug, item in existing.items():
        if slug in incoming or not item.is_builtin:
            continue
        ok, _reason = can_delete_slug(slug, installed=installed)
        if not ok:
            kept_installed += 1
            continue
        item.delete()
        removed += 1
    return {
        "added": added,
        "updated": updated,
        "removed": removed,
        "kept_manual": kept_manual,
        "kept_installed": kept_installed,
    }


def refresh_catalog():
    apps, error = fetch_catalog()
    if error:
        return None, error
    return apply_catalog(apps), ""


def all_services():
    ensure_catalog_seeded()
    return [row.to_entry() for row in CatalogItem.objects.all()]


def get_item(slug):
    ensure_catalog_seeded()
    row = CatalogItem.objects.filter(slug=slug).first()
    return row.to_entry() if row else None


def list_catalog_rows():
    ensure_catalog_seeded()
    installed = set(
        InstalledService.objects.filter(
            status__in=("running", "stopped", "installing")
        ).values_list("slug", flat=True)
    )
    rows = []
    for item in CatalogItem.objects.all():
        deletable, reason = can_delete_slug(item.slug, installed=installed)
        rows.append(
            {
                "slug": item.slug,
                "name": item.name,
                "tagline": item.tagline,
                "description": item.description,
                "category": item.category,
                "repo": item.repo,
                "website": item.website,
                "icon": item.icon,
                "default_port": item.default_port,
                "container_port": item.container_port,
                "path": item.path,
                "widget_type": item.widget_type,
                "compose": item.compose,
                "install_options": item.install_options,
                "is_builtin": item.is_builtin,
                "sort_order": item.sort_order,
                "installed": item.slug in installed,
                "can_delete": deletable,
                "delete_block_reason": reason,
            }
        )
    return rows


def _slug_has_data_volumes(slug):
    prefix = f"cc-{slug}-"
    try:
        client = get_docker_client()
        for vol in client.volumes.list():
            name = vol.name
            labels = vol.attrs.get("Labels") or {}
            if name.startswith(prefix) or labels.get(DOCKER_LABEL_SLUG) == slug:
                return True
    except docker.errors.DockerException:
        pass
    return False


def can_delete_slug(slug, installed=None):
    if installed is None:
        installed = set(
            InstalledService.objects.filter(
                status__in=("running", "stopped", "installing")
            ).values_list("slug", flat=True)
        )
    if slug in installed:
        return False, "Uninstall this service before removing it from the catalog."
    if _slug_has_data_volumes(slug):
        return False, "Data volumes still exist. Uninstall with remove data first."
    return True, ""


def validate_catalog_payload(payload, slug=""):
    errors = []
    raw_slug = (payload.get("slug") or slug or "").strip().lower()
    if not raw_slug:
        errors.append("Slug is required.")
    elif not SLUG_RE.fullmatch(raw_slug):
        errors.append("Slug must use lowercase letters, numbers, and hyphens.")
    name = (payload.get("name") or "").strip()
    if not name:
        errors.append("Name is required.")
    category = (payload.get("category") or "").strip()
    if not category:
        errors.append("Category is required.")
    compose = (payload.get("compose") or "").strip()
    if not compose and not (payload.get("repo") or "").strip():
        errors.append("Compose YAML or a GitHub repo is required.")
    port = payload.get("default_port", 8080)
    try:
        port = int(port)
        if port < 1 or port > 65535:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("Default port must be between 1 and 65535.")
    return errors, raw_slug


def save_catalog_item(payload, slug=""):
    errors, raw_slug = validate_catalog_payload(payload, slug=slug)
    if errors:
        return None, errors
    if slug and slug != raw_slug:
        return None, ["Slug cannot be changed."]
    if not slug and CatalogItem.objects.filter(slug=raw_slug).exists():
        return None, [f"Slug “{raw_slug}” already exists."]

    cp = payload.get("container_port") or 0
    try:
        cp = int(cp)
    except (TypeError, ValueError):
        cp = 0

    defaults = {
        "name": payload.get("name", "").strip(),
        "tagline": (payload.get("tagline") or "").strip(),
        "description": (payload.get("description") or payload.get("tagline") or "").strip(),
        "category": payload.get("category", "").strip(),
        "repo": (payload.get("repo") or "").strip(),
        "website": (payload.get("website") or "").strip(),
        "icon": (payload.get("icon") or "").strip(),
        "default_port": int(payload.get("default_port") or 8080),
        "container_port": cp,
        "path": (payload.get("path") or "/").strip() or "/",
        "widget_type": (payload.get("widget_type") or "none").strip() or "none",
        "compose": (payload.get("compose") or "").strip(),
        "install_options": (payload.get("install_options") or "").strip(),
    }
    if slug:
        item = CatalogItem.objects.filter(slug=slug).first()
        if not item:
            return None, ["Unknown catalog entry."]
        for key, value in defaults.items():
            setattr(item, key, value)
        item.save()
    else:
        max_order = CatalogItem.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
        item = CatalogItem.objects.create(
            slug=raw_slug,
            is_builtin=False,
            sort_order=max_order + 1,
            **defaults,
        )
    return item, []


def delete_catalog_item(slug):
    item = CatalogItem.objects.filter(slug=slug).first()
    if not item:
        return False, "Unknown catalog entry."
    ok, reason = can_delete_slug(slug)
    if not ok:
        return False, reason
    item.delete()
    return True, "Removed"
