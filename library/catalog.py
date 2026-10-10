"""Addon list and catalog lookups. Built-in apps live in catalog/apps.json."""

import re

ADDONS = [
    {
        "slug": "notes",
        "name": "Notes",
        "description": "Personal notes that use the same Control Center login. Keep short lists, reminders, and shared household text in one place.",
        "url_name": "notes:list",
        "url_prefix": "/notes/",
        "category": "Productivity",
        "icon": "note",
        "removable": True,
    },
]

def get_service_by_slug(slug):
    from .catalog_store import get_item

    return get_item(slug)


def all_services():
    from .catalog_store import all_services as list_services

    return list_services()


def services_by_category():
    from .catalog_store import all_services

    grouped = {}
    for entry in all_services():
        grouped.setdefault(entry["category"], []).append(entry)
    return grouped


def service_categories():
    from .catalog_store import all_services

    seen = []
    for entry in all_services():
        if entry["category"] not in seen:
            seen.append(entry["category"])
    return seen


def get_docker_spec(entry):
    """Return docker install spec, parsing compose when needed."""
    if entry.get("docker"):
        return entry["docker"]

    compose = entry.get("compose", "")
    image = ""
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped.startswith("image:"):
            image = stripped.split("image:", 1)[1].strip()
            break

    host_port_hint = entry.get("default_port", 8080)
    container_port = int(entry.get("container_port") or 0) or host_port_hint
    port_match = re.search(r'-\s*"(\d+):(\d+)"', compose)
    if port_match:
        host_port_hint = int(port_match.group(1))
        if not entry.get("container_port"):
            container_port = int(port_match.group(2))

    volumes = []
    env = {}
    extra_hosts = {}
    pid_mode = ""
    section = None
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped.startswith("pid:"):
            pid_mode = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            continue
        if stripped == "volumes:":
            section = "volumes"
            continue
        if stripped == "environment:":
            section = "environment"
            continue
        if stripped == "extra_hosts:":
            section = "extra_hosts"
            continue
        if stripped.endswith(":") and not stripped.startswith("-"):
            section = None
        if section == "volumes" and stripped.startswith("-"):
            vol = stripped.lstrip("- ").strip().strip('"').strip("'")
            if ":" in vol:
                host_part, container_part = vol.rsplit(":", 1)
                container_path = container_part.split(":")[0]
                if host_part.startswith("/") and not host_part.startswith("./"):
                    continue
                volumes.append(container_path)
        if section == "environment" and ":" in stripped:
            key, _, value = stripped.partition(":")
            env[key.strip()] = value.strip().strip('"').strip("'")
        if section == "extra_hosts" and stripped.startswith("-"):
            item = stripped.lstrip("- ").strip().strip('"').strip("'")
            if ":" in item:
                hostname, _, addr = item.partition(":")
                extra_hosts[hostname.strip()] = addr.strip()

    return {
        "image": image,
        "container_port": container_port,
        "host_port_hint": host_port_hint,
        "volumes": volumes,
        "env": env,
        "pid_mode": pid_mode,
        "extra_hosts": extra_hosts,
    }


def all_categories():
    from .catalog_store import ensure_catalog_seeded
    from .models import CatalogItem

    categories = []
    for entry in ADDONS:
        if entry["category"] not in categories:
            categories.append(entry["category"])
    ensure_catalog_seeded()
    for item in CatalogItem.objects.all():
        if item.category not in categories:
            categories.append(item.category)
    return categories


def build_catalog_items(
    addon_enabled_map,
    installed_map,
    release_map,
    app_version="",
    service_cards=None,
):
    """Normalized catalog rows for the unified library grid."""
    from .catalog_store import ensure_catalog_seeded
    from .icons import icon_url_for_entry
    from .models import CatalogItem

    ensure_catalog_seeded()

    if service_cards is None:
        from dashboard.models import Service

        service_cards = {
            row.catalog_slug: row.id
            for row in Service.objects.exclude(catalog_slug="")
        }
    items = []
    for addon in ADDONS:
        enabled = addon_enabled_map.get(addon["slug"], True)
        items.append(
            {
                "type": "addon",
                "slug": addon["slug"],
                "name": addon["name"],
                "icon": addon.get("icon", ""),
                "icon_url": icon_url_for_entry(
                    addon["slug"], addon.get("icon", ""), name=addon.get("name", "")
                ),
                "description": addon["description"],
                "category": addon["category"],
                "installed": enabled,
                "status": "running" if enabled else "disabled",
                "repo_url": "",
                "version": app_version,
                "url_name": addon.get("url_name", ""),
                "service_id": None,
            }
        )
    for item in CatalogItem.objects.all():
        entry = item.to_entry()
        inst = installed_map.get(entry["slug"])
        installed = inst is not None and inst.status in (
            "running",
            "stopped",
            "installing",
        )
        status = inst.status if inst else "none"
        service_id = service_cards.get(entry["slug"])
        repo = entry.get("repo", "")
        items.append(
            {
                "type": "service",
                "slug": entry["slug"],
                "name": entry["name"],
                "icon": "",
                "icon_url": icon_url_for_entry(
                    entry["slug"], entry.get("icon", ""), name=entry.get("name", "")
                ),
                "description": item.description or entry.get("tagline", ""),
                "category": entry["category"],
                "installed": installed and inst.status != "installing",
                "status": status,
                "managed": inst.managed if inst else True,
                "host_port": inst.host_port if inst else 0,
                "container_name": inst.container_name if inst else "",
                "repo_url": f"https://github.com/{repo}" if repo else "",
                "version": release_map.get(repo, ""),
                "url_name": "",
                "service_id": service_id,
                "needs_credentials": entry.get("install_options") == "admin-credentials",
            }
        )
    return items

