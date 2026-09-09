"""DB-backed library catalog: seed, CRUD, and delete guards."""

import re

import docker

from .catalog import LIBRARY_DESCRIPTIONS, SERVICES
from .installer import DOCKER_LABEL_SLUG, get_docker_client
from .models import CatalogItem, InstalledService

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _item_fields(entry, sort_order):
    slug = entry["slug"]
    return {
        "slug": slug,
        "name": entry["name"],
        "tagline": entry.get("tagline", ""),
        "description": LIBRARY_DESCRIPTIONS.get(slug, entry.get("tagline", "")),
        "category": entry["category"],
        "repo": entry.get("repo", ""),
        "website": entry.get("website", ""),
        "icon": entry.get("icon", ""),
        "default_port": int(entry.get("default_port") or 8080),
        "container_port": int(entry.get("container_port") or 0),
        "path": entry.get("path", "/") or "/",
        "widget_type": entry.get("widget_type", "none") or "none",
        "compose": entry.get("compose", ""),
        "install_options": entry.get("install_options", "") or "",
        "is_builtin": True,
        "sort_order": sort_order,
    }


def seed_builtin_catalog():
    if CatalogItem.objects.exists():
        return 0
    rows = [
        CatalogItem(**_item_fields(entry, idx))
        for idx, entry in enumerate(SERVICES)
    ]
    CatalogItem.objects.bulk_create(rows)
    return len(rows)


def sync_missing_builtins():
    existing = set(CatalogItem.objects.values_list("slug", flat=True))
    max_order = (
        CatalogItem.objects.order_by("-sort_order").values_list("sort_order", flat=True).first()
        or 0
    )
    rows = []
    for entry in SERVICES:
        if entry["slug"] in existing:
            continue
        max_order += 1
        rows.append(CatalogItem(**_item_fields(entry, max_order)))
    if rows:
        CatalogItem.objects.bulk_create(rows)
    return len(rows)


def ensure_catalog_seeded():
    if not CatalogItem.objects.exists():
        seed_builtin_catalog()
        return
    sync_missing_builtins()


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
