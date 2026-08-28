"""Docker install/uninstall and dashboard card sync for library services."""

import logging
import re
import socket
import threading

import docker
from django.conf import settings

from core.models import SiteSettings
from core.site_settings import clear_site_settings_cache, get_site_settings
from dashboard.models import Service, ServiceCategory
from dashboard.presets import apply_preset_metrics

from .catalog import get_docker_spec, get_service_by_slug
from .models import InstalledService

logger = logging.getLogger(__name__)

DOCKER_LABEL_SLUG = "control-center.slug"


def get_docker_client():
    return docker.DockerClient(base_url=settings.DOCKER_HOST)


def detect_services_host():
    site = SiteSettings.load()
    if site.services_host.strip():
        return site.services_host.strip()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        host = sock.getsockname()[0]
        sock.close()
        site.services_host = host
        site.save(update_fields=["services_host"])
        clear_site_settings_cache()
        return host
    except OSError:
        return "127.0.0.1"


def services_host():
    host = get_site_settings().services_host.strip()
    return host or detect_services_host()


def _collect_used_ports(client):
    used = set()
    for row in InstalledService.objects.exclude(host_port=0):
        used.add(row.host_port)
    for container in client.containers.list(all=True):
        ports = container.attrs.get("NetworkSettings", {}).get("Ports") or {}
        for bindings in ports.values():
            if not bindings:
                continue
            for binding in bindings:
                if binding.get("HostPort"):
                    used.add(int(binding["HostPort"]))
    return used


def pick_host_port(client, start_port):
    used = _collect_used_ports(client)
    port = max(start_port, 1024)
    while port in used:
        port += 1
        if port > 65535:
            raise RuntimeError("No free host port available")
    return port


def _image_version(client, image):
    try:
        img = client.images.get(image)
        labels = img.attrs.get("Config", {}).get("Labels") or {}
        version = labels.get("org.opencontainers.image.version", "").strip()
        if version:
            return version[:64]
        tags = img.tags
        if tags:
            tag = tags[0].split(":")[-1]
            if tag and tag != "latest":
                return tag[:64]
    except docker.errors.DockerException as exc:
        logger.debug("Could not read image version for %s: %s", image, exc)
    if ":" in image:
        return image.rsplit(":", 1)[-1][:64]
    return ""


def _remove_container(client, name):
    try:
        container = client.containers.get(name)
        container.stop(timeout=15)
        container.remove(force=True)
    except docker.errors.NotFound:
        pass


def _collect_container_volume_names(client, container_name):
    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        return []
    names = []
    for mount in container.attrs.get("Mounts") or []:
        if mount.get("Type") == "volume" and mount.get("Name"):
            names.append(mount["Name"])
    return names


def _remove_service_volumes(client, slug, remove_data, extra_volume_names=None):
    if not remove_data:
        return
    extra = set(extra_volume_names or [])
    prefix = f"cc-{slug}-"
    for vol in client.volumes.list():
        name = vol.name
        labels = vol.attrs.get("Labels") or {}
        if (
            name in extra
            or name.startswith(prefix)
            or labels.get(DOCKER_LABEL_SLUG) == slug
        ):
            try:
                vol.remove(force=True)
            except docker.errors.APIError as exc:
                logger.warning("Could not remove volume %s: %s", name, exc)


def create_dashboard_card(slug, entry, host_port):
    host = services_host()
    category_name = entry.get("category", "Services")
    category, _ = ServiceCategory.objects.get_or_create(
        name=category_name,
        defaults={"sort_order": 99},
    )
    Service.objects.filter(catalog_slug=slug).delete()
    widget_type = entry.get("widget_type", "none")
    service = Service(
        category=category,
        name=entry["name"],
        description=entry.get("tagline", ""),
        host=host,
        port=host_port,
        path=entry.get("path", "/") or "/",
        icon=entry.get("icon", ""),
        catalog_slug=slug,
        widget_type=widget_type,
        is_public=False,
        enabled=True,
    )
    if widget_type != "none":
        service.widget_url = f"http://{host}:{host_port}"
    service.save()
    if widget_type == "pihole":
        apply_preset_metrics(service, "pihole")
    elif widget_type == "speedtest":
        apply_preset_metrics(service, "speedtest")
    return service


def delete_dashboard_card(slug):
    Service.objects.filter(catalog_slug=slug).delete()


def _install_worker(slug):
    entry = get_service_by_slug(slug)
    if not entry:
        InstalledService.objects.filter(slug=slug).update(
            status=InstalledService.Status.ERROR,
            error="Unknown catalog entry",
        )
        return
    spec = get_docker_spec(entry)
    image = spec.get("image", "").strip()
    if not image:
        InstalledService.objects.filter(slug=slug).update(
            status=InstalledService.Status.ERROR,
            error="No Docker image configured",
        )
        return

    container_name = f"cc-{slug}"
    container_port = int(spec.get("container_port") or entry.get("default_port") or 8080)
    start_port = int(spec.get("host_port_hint") or entry.get("default_port") or container_port)

    try:
        client = get_docker_client()
        client.images.pull(image)
        host_port = pick_host_port(client, start_port)
        _remove_container(client, container_name)

        volume_map = {}
        for idx, container_path in enumerate(spec.get("volumes") or []):
            clean_path = container_path.split(":")[0].strip()
            if not clean_path.startswith("/"):
                continue
            vol_name = f"cc-{slug}-{idx}"
            try:
                client.volumes.create(
                    name=vol_name,
                    labels={DOCKER_LABEL_SLUG: slug},
                )
            except docker.errors.APIError:
                pass
            volume_map[vol_name] = {"bind": clean_path, "mode": "rw"}

        ports = {f"{container_port}/tcp": host_port}
        env = spec.get("env") or {}

        client.containers.run(
            image,
            name=container_name,
            detach=True,
            ports=ports,
            volumes=volume_map or None,
            environment=env or None,
            labels={DOCKER_LABEL_SLUG: slug},
            restart_policy={"Name": "unless-stopped"},
        )

        installed_version = _image_version(client, image)
        InstalledService.objects.filter(slug=slug).update(
            host_port=host_port,
            installed_version=installed_version,
            status=InstalledService.Status.RUNNING,
            error="",
        )
        create_dashboard_card(slug, entry, host_port)
    except Exception as exc:  # noqa: BLE001 - background worker must record failure
        logger.exception("Install failed for %s", slug)
        InstalledService.objects.filter(slug=slug).update(
            status=InstalledService.Status.ERROR,
            error=str(exc)[:500],
        )


def start_install(slug):
    entry = get_service_by_slug(slug)
    if not entry:
        return False, "Unknown service"
    existing = InstalledService.objects.filter(slug=slug).first()
    if existing and existing.status in (
        InstalledService.Status.RUNNING,
        InstalledService.Status.STOPPED,
    ):
        return False, "Already installed"
    if existing and existing.status == InstalledService.Status.INSTALLING:
        return False, "Install already in progress"

    container_name = f"cc-{slug}"
    InstalledService.objects.update_or_create(
        slug=slug,
        defaults={
            "container_name": container_name,
            "host_port": 0,
            "status": InstalledService.Status.INSTALLING,
            "managed": True,
            "error": "",
        },
    )
    thread = threading.Thread(
        target=_install_worker,
        args=(slug,),
        name=f"install-{slug}",
        daemon=True,
    )
    thread.start()
    return True, "Installing"


def uninstall(slug, remove_data=False):
    row = InstalledService.objects.filter(slug=slug).first()
    container_name = row.container_name if row else f"cc-{slug}"
    try:
        client = get_docker_client()
        extra_volumes = []
        if remove_data and row and not row.managed:
            extra_volumes = _collect_container_volume_names(client, container_name)
        _remove_container(client, container_name)
        _remove_service_volumes(
            client,
            slug,
            remove_data,
            extra_volume_names=extra_volumes,
        )
    except docker.errors.DockerException as exc:
        logger.warning("Docker uninstall issue for %s: %s", slug, exc)
        InstalledService.objects.filter(slug=slug).update(
            status=InstalledService.Status.ERROR,
            error=str(exc)[:500],
        )
        return False, str(exc)

    delete_dashboard_card(slug)
    InstalledService.objects.filter(slug=slug).delete()
    return True, "Uninstalled"


def status_payload(slug):
    row = InstalledService.objects.filter(slug=slug).first()
    if not row:
        return {"slug": slug, "installed": False, "status": "none", "managed": True}
    installed = row.status in (
        InstalledService.Status.RUNNING,
        InstalledService.Status.STOPPED,
    )
    return {
        "slug": slug,
        "installed": installed,
        "status": row.status,
        "host_port": row.host_port,
        "installed_version": row.installed_version,
        "managed": row.managed,
        "error": row.error,
    }
