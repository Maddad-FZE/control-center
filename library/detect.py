"""Detect already-running Docker containers and match them to library catalog entries."""

import logging

import docker
from django.core.cache import cache

from .catalog import SERVICES, get_docker_spec
from .installer import DOCKER_LABEL_SLUG, get_docker_client, _image_version
from .models import InstalledService

logger = logging.getLogger(__name__)

SYNC_LOCK_KEY = "library:detect_sync"
SYNC_LOCK_TTL = 30


def _normalize_image_repo(image_ref):
    """Strip registry host, tag, and digest to a comparable repository path."""
    if not image_ref:
        return ""
    ref = image_ref.strip()
    if "@" in ref:
        ref = ref.split("@", 1)[0]
    if ":" in ref and not ref.rsplit(":", 1)[-1].isdigit():
        ref = ref.rsplit(":", 1)[0]
    # Drop registry host when it looks like a hostname (contains a dot before first slash)
    if "/" in ref:
        first, rest = ref.split("/", 1)
        if "." in first or first == "localhost":
            ref = rest
    return ref.lower().strip()


def _slug_from_repo(repo):
    if "/" in repo:
        return repo.rsplit("/", 1)[-1]
    return repo


def _build_catalog_index():
    """Map normalized image repo and slug aliases to catalog slugs."""
    by_repo = {}
    by_slug_tail = {}
    by_slug = {}

    for entry in SERVICES:
        slug = entry["slug"]
        by_slug[slug] = slug
        spec = get_docker_spec(entry)
        image = spec.get("image", "").strip()
        if image:
            norm = _normalize_image_repo(image)
            if norm:
                by_repo[norm] = slug
            tail = _slug_from_repo(norm)
            if tail:
                by_slug_tail[tail] = slug
        by_slug_tail[slug] = slug

    return by_repo, by_slug_tail, by_slug


def _host_port_from_container(container, preferred_container_port=None):
    ports = container.attrs.get("NetworkSettings", {}).get("Ports") or {}
    preferred_key = None
    if preferred_container_port:
        preferred_key = f"{preferred_container_port}/tcp"

    if preferred_key and ports.get(preferred_key):
        bindings = ports[preferred_key]
        if bindings and bindings[0].get("HostPort"):
            return int(bindings[0]["HostPort"])

    for key, bindings in ports.items():
        if not key.endswith("/tcp") or not bindings:
            continue
        host_port = bindings[0].get("HostPort")
        if host_port:
            return int(host_port)
    return 0


def _container_status(container):
    state = container.attrs.get("State", {}).get("Status", container.status)
    if state == "running":
        return InstalledService.Status.RUNNING
    if state in ("exited", "dead", "created", "paused"):
        return InstalledService.Status.STOPPED
    return InstalledService.Status.STOPPED


def _match_container_to_slug(container, by_repo, by_slug_tail, by_slug):
    labels = container.attrs.get("Config", {}).get("Labels") or {}
    if labels.get(DOCKER_LABEL_SLUG):
        return None

    name = container.name.lstrip("/").lower()
    image_ref = ""
    if container.image.tags:
        image_ref = container.image.tags[0]
    else:
        image_ref = container.image.short_id

    norm = _normalize_image_repo(image_ref)
    if norm and norm in by_repo:
        return by_repo[norm]

    tail = _slug_from_repo(norm)
    if tail and tail in by_slug_tail:
        return by_slug_tail[tail]

    for slug in by_slug:
        if name == slug or name.endswith(f"-{slug}") or f"-{slug}-" in name:
            return slug
        if slug in name:
            return slug

    return None


def _catalog_container_port(slug):
    from .catalog import get_service_by_slug

    entry = get_service_by_slug(slug)
    if not entry:
        return None
    spec = get_docker_spec(entry)
    port = spec.get("container_port") or entry.get("default_port")
    return int(port) if port else None


def sync_detected_services():
    """Upsert unmanaged InstalledService rows for detected catalog containers."""
    by_repo, by_slug_tail, by_slug = _build_catalog_index()
    client = get_docker_client()
    containers = client.containers.list(all=True)

    seen_slugs = set()
    adopted = 0
    refreshed = 0

    for container in containers:
        slug = _match_container_to_slug(container, by_repo, by_slug_tail, by_slug)
        if not slug:
            continue

        existing = InstalledService.objects.filter(slug=slug).first()
        if existing and existing.managed:
            continue

        container_name = container.name.lstrip("/")
        preferred_port = _catalog_container_port(slug)
        host_port = _host_port_from_container(container, preferred_port)
        image_ref = container.image.tags[0] if container.image.tags else ""
        installed_version = _image_version(client, image_ref) if image_ref else ""
        status = _container_status(container)

        defaults = {
            "container_name": container_name,
            "host_port": host_port,
            "installed_version": installed_version,
            "status": status,
            "managed": False,
            "error": "",
        }

        if existing:
            InstalledService.objects.filter(slug=slug, managed=False).update(**defaults)
            refreshed += 1
        else:
            InstalledService.objects.create(slug=slug, **defaults)
            adopted += 1

        seen_slugs.add(slug)

    removed = InstalledService.objects.filter(managed=False).exclude(slug__in=seen_slugs).delete()[0]

    return {
        "adopted": adopted,
        "refreshed": refreshed,
        "removed": removed,
        "detected": len(seen_slugs),
    }


def maybe_sync_detected():
    """Run detection if the short-lived cache lock is available."""
    if not cache.add(SYNC_LOCK_KEY, "1", SYNC_LOCK_TTL):
        return None
    try:
        return sync_detected_services()
    except docker.errors.DockerException as exc:
        logger.warning("Docker detection failed: %s", exc)
        return {"error": str(exc)}
