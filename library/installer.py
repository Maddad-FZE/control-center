"""Docker install/uninstall and dashboard card sync for library services."""

import base64
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request

import docker
from django.conf import settings

from core.models import SiteSettings
from core.site_settings import clear_site_settings_cache, get_site_settings
from dashboard.models import Service, ServiceCategory
from dashboard.presets import apply_preset_metrics

from .catalog import LIBRARY_DESCRIPTIONS, get_docker_spec, get_service_by_slug
from .icons import icon_url_for_entry
from .models import InstalledService

logger = logging.getLogger(__name__)

DOCKER_LABEL_SLUG = "control-center.slug"
DOCKER_LABEL_ROLE = "control-center.role"

NEXTCLOUD_SLUG = "nextcloud"
NEXTCLOUD_DB_IMAGE = "postgres:16-alpine"
NEXTCLOUD_DB_CONTAINER = "cc-nextcloud-db"
NEXTCLOUD_NETWORK = "cc-nextcloud-net"
NEXTCLOUD_DB_VOLUME = "cc-nextcloud-db-0"
POSTGRES_WAIT_SECONDS = 60
NEXTCLOUD_READY_SECONDS = 300
ADMIN_USER_RE = re.compile(r"^[A-Za-z0-9._@-]+$")

BOOKSTACK_SLUG = "bookstack"
BOOKSTACK_IMAGE = "lscr.io/linuxserver/bookstack:latest"
BOOKSTACK_DB_IMAGE = "mariadb:11"
BOOKSTACK_DB_CONTAINER = "cc-bookstack-db"
BOOKSTACK_NETWORK = "cc-bookstack-net"
BOOKSTACK_DB_VOLUME = "cc-bookstack-db-0"
MARIADB_WAIT_SECONDS = 60

ODYSSEUS_SLUG = "odysseus"
ODYSSEUS_IMAGE = "cc-odysseus:local"
ODYSSEUS_NETWORK = "cc-odysseus-net"
ODYSSEUS_CHROMA = "cc-odysseus-chroma"
ODYSSEUS_SEARXNG = "cc-odysseus-searxng"
ODYSSEUS_NTFY = "cc-odysseus-ntfy"
ODYSSEUS_SIDECARS = (ODYSSEUS_CHROMA, ODYSSEUS_SEARXNG, ODYSSEUS_NTFY)
ODYSSEUS_GIT_REFS = (
    "https://github.com/odysseus-dev/odysseus.git#main",
    "https://github.com/odysseus-dev/odysseus.git#dev",
)
HOST_GATEWAY = {"host.docker.internal": "host-gateway"}

SECURO_SLUG = "securo"
SECURO_FRONTEND_IMAGE = "ghcr.io/securo-finance/securo-frontend:latest"
SECURO_BACKEND_IMAGE = "ghcr.io/securo-finance/securo-backend:latest"
SECURO_DB_IMAGE = "pgvector/pgvector:pg16"
SECURO_REDIS_IMAGE = "redis:8-alpine"
SECURO_BACKEND = "cc-securo-backend"
SECURO_DB = "cc-securo-db"
SECURO_REDIS = "cc-securo-redis"
SECURO_WORKER = "cc-securo-worker"
SECURO_BEAT = "cc-securo-beat"
SECURO_NETWORK = "cc-securo-net"
SECURO_SIDECARS = (SECURO_BACKEND, SECURO_DB, SECURO_REDIS, SECURO_WORKER, SECURO_BEAT)
SECURO_DB_VOLUME = "cc-securo-db-0"
SECURO_ATTACHMENTS_VOLUME = "cc-securo-attachments"
SECURO_KNOWLEDGE_VOLUME = "cc-securo-agent-knowledge"
SECURO_EMBEDDINGS_VOLUME = "cc-securo-agent-embeddings"
REDIS_WAIT_SECONDS = 60


def _clear_uptime_cache_if_kuma(slug):
    if slug != "uptime-kuma":
        return
    from django.core.cache import cache

    cache.delete("uptime:payload")


TUNNEL_SLUG = "cloudflare-tunnel"
NO_CARD_ON_INSTALL = frozenset({"uptime-kuma", TUNNEL_SLUG})

PRIVATE_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
DOCKER_NETS = (
    ipaddress.ip_network("172.17.0.0/16"),
    ipaddress.ip_network("172.18.0.0/16"),
    ipaddress.ip_network("172.19.0.0/16"),
    ipaddress.ip_network("172.20.0.0/14"),
)


def get_docker_client():
    return docker.DockerClient(base_url=settings.DOCKER_HOST)


def _is_usable_lan_host(value):
    raw = (value or "").strip()
    if not raw or raw in ("localhost", "127.0.0.1", "::1"):
        return False
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return "." in raw or raw[0].isalpha()
    if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
        return False
    for net in DOCKER_NETS:
        if addr in net:
            return False
    if addr.version == 4:
        return any(addr in net for net in PRIVATE_NETS) or not addr.is_private
    return True


def _host_from_request(request):
    if request is None:
        return ""
    forwarded = (request.META.get("HTTP_X_FORWARDED_HOST") or "").split(",")[0].strip()
    host = forwarded or request.get_host()
    host = host.split(":")[0].strip("[]")
    return host if _is_usable_lan_host(host) else ""


def _host_from_interfaces():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        host = sock.getsockname()[0]
        sock.close()
        if _is_usable_lan_host(host):
            return host
    except OSError:
        pass
    return ""


def remember_services_host(host):
    host = (host or "").strip()
    if not _is_usable_lan_host(host):
        return ""
    site = SiteSettings.load()
    if site.services_host.strip() == host:
        return host
    site.services_host = host
    site.save(update_fields=["services_host"])
    clear_site_settings_cache()
    return host


def detect_services_host(request=None):
    site = SiteSettings.load()
    stored = site.services_host.strip()
    if _is_usable_lan_host(stored):
        return stored
    if stored:
        site.services_host = ""
        site.save(update_fields=["services_host"])
        clear_site_settings_cache()

    for candidate in (
        _host_from_request(request),
        os.environ.get("SERVICES_HOST", "").strip() or getattr(settings, "SERVICES_HOST", ""),
        _host_from_interfaces(),
    ):
        if _is_usable_lan_host(candidate):
            return remember_services_host(candidate) or candidate
    return "127.0.0.1"


def services_host(request=None):
    stored = get_site_settings().services_host.strip()
    if _is_usable_lan_host(stored):
        return stored
    return detect_services_host(request)


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


def _remove_labeled_containers(client, slug):
    label = f"{DOCKER_LABEL_SLUG}={slug}"
    try:
        containers = client.containers.list(all=True, filters={"label": label})
    except docker.errors.DockerException:
        return
    for container in containers:
        try:
            container.stop(timeout=15)
            container.remove(force=True)
        except docker.errors.APIError as exc:
            logger.warning("Could not remove container %s: %s", container.name, exc)


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


def _remove_network(client, name):
    try:
        client.networks.get(name).remove()
    except docker.errors.NotFound:
        pass
    except docker.errors.APIError as exc:
        logger.warning("Could not remove network %s: %s", name, exc)


def _ensure_network(client, name, labels):
    try:
        client.networks.get(name)
    except docker.errors.NotFound:
        client.networks.create(name, labels=labels)


def _ensure_volume(client, name, labels):
    try:
        client.volumes.create(name=name, labels=labels)
    except docker.errors.APIError:
        pass


def _env_value(env_list, key):
    prefix = f"{key}="
    for item in env_list or []:
        if isinstance(item, str) and item.startswith(prefix):
            return item[len(prefix) :]
    return ""


def _previous_container_env(client, container_name, key):
    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        return ""
    env = (container.attrs or {}).get("Config", {}).get("Env") or []
    return _env_value(env, key)


def _previous_postgres_password(client, container_name):
    return _previous_container_env(client, container_name, "POSTGRES_PASSWORD")


def validate_nextcloud_credentials(admin_user, admin_password):
    user = (admin_user or "").strip()
    password = admin_password or ""
    if not user:
        return "Admin username is required."
    if len(user) > 64 or not ADMIN_USER_RE.fullmatch(user):
        return "Admin username may only use letters, numbers, dots, underscores, @, and hyphens."
    if len(password) < 10:
        return "Admin password must be at least 10 characters."
    if len(password) > 128:
        return "Admin password is too long."
    if password.lower() == user.lower():
        return "Admin password must be different from the username."
    return ""


def _wait_for_postgres(
    container, timeout=POSTGRES_WAIT_SECONDS, *, user="nextcloud", database="nextcloud"
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = container.exec_run(["pg_isready", "-U", user, "-d", database])
            if getattr(result, "exit_code", 1) == 0:
                return
        except docker.errors.APIError:
            pass
        time.sleep(1)
    raise RuntimeError("Postgres did not become ready")


def _wait_for_redis(container, timeout=REDIS_WAIT_SECONDS):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = container.exec_run(["redis-cli", "ping"])
            if getattr(result, "exit_code", 1) == 0:
                return
        except docker.errors.APIError:
            pass
        time.sleep(1)
    raise RuntimeError("Redis did not become ready")


def _wait_for_nextcloud(url, timeout=NEXTCLOUD_READY_SECONDS):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            if data.get("installed") is True:
                return True
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
            pass
        time.sleep(2)
    logger.warning("Nextcloud did not finish setup in time")
    return False


def _install_nextcloud(client, entry, spec, options):
    admin_user = (options.get("admin_user") or "").strip()
    admin_password = options.get("admin_password") or ""
    error = validate_nextcloud_credentials(admin_user, admin_password)
    if error:
        raise RuntimeError(error)

    image = spec.get("image", "").strip() or "nextcloud:latest"
    client.images.pull(image)
    client.images.pull(NEXTCLOUD_DB_IMAGE)

    db_password = _previous_postgres_password(client, NEXTCLOUD_DB_CONTAINER)
    if not db_password:
        db_password = secrets.token_urlsafe(32)

    _remove_container(client, f"cc-{NEXTCLOUD_SLUG}")
    _remove_container(client, NEXTCLOUD_DB_CONTAINER)

    labels = {DOCKER_LABEL_SLUG: NEXTCLOUD_SLUG}
    _ensure_network(client, NEXTCLOUD_NETWORK, labels)
    _ensure_volume(client, f"cc-{NEXTCLOUD_SLUG}-0", labels)
    _ensure_volume(client, NEXTCLOUD_DB_VOLUME, labels)

    db_env = {
        "POSTGRES_DB": "nextcloud",
        "POSTGRES_USER": "nextcloud",
        "POSTGRES_PASSWORD": db_password,
    }
    db_container = client.containers.run(
        NEXTCLOUD_DB_IMAGE,
        name=NEXTCLOUD_DB_CONTAINER,
        detach=True,
        network=NEXTCLOUD_NETWORK,
        volumes={NEXTCLOUD_DB_VOLUME: {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
        environment=db_env,
        labels={**labels, DOCKER_LABEL_ROLE: "db"},
        restart_policy={"Name": "unless-stopped"},
    )
    _wait_for_postgres(db_container)

    host_port = pick_host_port(client, int(spec.get("host_port_hint") or 8080))
    host = services_host()
    app_env = {
        "POSTGRES_HOST": NEXTCLOUD_DB_CONTAINER,
        "POSTGRES_DB": "nextcloud",
        "POSTGRES_USER": "nextcloud",
        "POSTGRES_PASSWORD": db_password,
        "NEXTCLOUD_ADMIN_USER": admin_user,
        "NEXTCLOUD_ADMIN_PASSWORD": admin_password,
        "NEXTCLOUD_TRUSTED_DOMAINS": f"{host} {host}:{host_port} localhost",
    }
    client.containers.run(
        image,
        name=f"cc-{NEXTCLOUD_SLUG}",
        detach=True,
        network=NEXTCLOUD_NETWORK,
        ports={"80/tcp": host_port},
        volumes={f"cc-{NEXTCLOUD_SLUG}-0": {"bind": "/var/www/html", "mode": "rw"}},
        environment=app_env,
        labels=labels,
        restart_policy={"Name": "unless-stopped"},
    )
    _wait_for_nextcloud(f"http://{host}:{host_port}/status.php")

    installed_version = _image_version(client, image)
    InstalledService.objects.filter(slug=NEXTCLOUD_SLUG).update(
        host_port=host_port,
        installed_version=installed_version,
        status=InstalledService.Status.RUNNING,
        error="",
    )
    create_dashboard_card(NEXTCLOUD_SLUG, entry, host_port)


def _bookstack_app_key():
    return "base64:" + base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def _wait_for_mariadb(container, root_password, timeout=MARIADB_WAIT_SECONDS):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = container.exec_run(
                [
                    "mysqladmin",
                    "ping",
                    "-h",
                    "127.0.0.1",
                    "-uroot",
                    f"-p{root_password}",
                    "--silent",
                ]
            )
            if getattr(result, "exit_code", 1) == 0:
                return
        except docker.errors.APIError:
            pass
        time.sleep(1)
    raise RuntimeError("MariaDB did not become ready")


def _install_bookstack(client, entry, spec):
    image = spec.get("image", "").strip() or BOOKSTACK_IMAGE
    client.images.pull(image)
    client.images.pull(BOOKSTACK_DB_IMAGE)

    db_password = _previous_container_env(client, BOOKSTACK_DB_CONTAINER, "MYSQL_PASSWORD")
    root_password = _previous_container_env(
        client, BOOKSTACK_DB_CONTAINER, "MYSQL_ROOT_PASSWORD"
    )
    app_key = _previous_container_env(client, f"cc-{BOOKSTACK_SLUG}", "APP_KEY")
    if not db_password:
        db_password = secrets.token_urlsafe(32)
    if not root_password:
        root_password = secrets.token_urlsafe(32)
    if not app_key:
        app_key = _bookstack_app_key()

    _remove_container(client, f"cc-{BOOKSTACK_SLUG}")
    _remove_container(client, BOOKSTACK_DB_CONTAINER)

    labels = {DOCKER_LABEL_SLUG: BOOKSTACK_SLUG}
    _ensure_network(client, BOOKSTACK_NETWORK, labels)
    _ensure_volume(client, f"cc-{BOOKSTACK_SLUG}-0", labels)
    _ensure_volume(client, BOOKSTACK_DB_VOLUME, labels)

    db_container = client.containers.run(
        BOOKSTACK_DB_IMAGE,
        name=BOOKSTACK_DB_CONTAINER,
        detach=True,
        network=BOOKSTACK_NETWORK,
        volumes={BOOKSTACK_DB_VOLUME: {"bind": "/var/lib/mysql", "mode": "rw"}},
        environment={
            "MYSQL_DATABASE": "bookstack",
            "MYSQL_USER": "bookstack",
            "MYSQL_PASSWORD": db_password,
            "MYSQL_ROOT_PASSWORD": root_password,
        },
        labels={**labels, DOCKER_LABEL_ROLE: "db"},
        restart_policy={"Name": "unless-stopped"},
    )
    _wait_for_mariadb(db_container, root_password)

    host_port = pick_host_port(client, int(spec.get("host_port_hint") or 6875))
    host = services_host()
    client.containers.run(
        image,
        name=f"cc-{BOOKSTACK_SLUG}",
        detach=True,
        network=BOOKSTACK_NETWORK,
        ports={"80/tcp": host_port},
        volumes={f"cc-{BOOKSTACK_SLUG}-0": {"bind": "/config", "mode": "rw"}},
        environment={
            "PUID": "1000",
            "PGID": "1000",
            "APP_URL": f"http://{host}:{host_port}",
            "APP_KEY": app_key,
            "DB_HOST": BOOKSTACK_DB_CONTAINER,
            "DB_PORT": "3306",
            "DB_DATABASE": "bookstack",
            "DB_USERNAME": "bookstack",
            "DB_PASSWORD": db_password,
        },
        labels=labels,
        restart_policy={"Name": "unless-stopped"},
    )

    installed_version = _image_version(client, image)
    InstalledService.objects.filter(slug=BOOKSTACK_SLUG).update(
        host_port=host_port,
        installed_version=installed_version,
        status=InstalledService.Status.RUNNING,
        error="",
    )
    create_dashboard_card(BOOKSTACK_SLUG, entry, host_port)


def _build_odysseus_image(client):
    errors = []
    for remote in ODYSSEUS_GIT_REFS:
        try:
            stream = client.api.build(
                remote=remote,
                tag=ODYSSEUS_IMAGE,
                rm=True,
                decode=True,
            )
            error = ""
            for chunk in stream or []:
                if isinstance(chunk, dict) and chunk.get("error"):
                    error = chunk["error"]
                    break
            if error:
                errors.append(f"{remote}: {error}")
                continue
            return ODYSSEUS_IMAGE
        except Exception as exc:  # noqa: BLE001 - try the next git ref
            errors.append(f"{remote}: {exc}")
    detail = "; ".join(errors) if errors else "unknown error"
    raise RuntimeError(f"Could not build Odysseus from Git. {detail}")


def _install_odysseus(client, entry, spec):
    labels = {DOCKER_LABEL_SLUG: ODYSSEUS_SLUG}
    _remove_labeled_containers(client, ODYSSEUS_SLUG)
    for name in (f"cc-{ODYSSEUS_SLUG}", *ODYSSEUS_SIDECARS):
        _remove_container(client, name)

    image = _build_odysseus_image(client)
    client.images.pull("chromadb/chroma:latest")
    client.images.pull("searxng/searxng:latest")
    client.images.pull("binwiederhier/ntfy:latest")

    _ensure_network(client, ODYSSEUS_NETWORK, labels)
    _ensure_volume(client, f"cc-{ODYSSEUS_SLUG}-0", labels)
    _ensure_volume(client, f"cc-{ODYSSEUS_SLUG}-chroma", labels)
    _ensure_volume(client, f"cc-{ODYSSEUS_SLUG}-searxng", labels)
    _ensure_volume(client, f"cc-{ODYSSEUS_SLUG}-ntfy", labels)

    client.containers.run(
        "chromadb/chroma:latest",
        name=ODYSSEUS_CHROMA,
        detach=True,
        network=ODYSSEUS_NETWORK,
        volumes={f"cc-{ODYSSEUS_SLUG}-chroma": {"bind": "/chroma/chroma", "mode": "rw"}},
        labels={**labels, DOCKER_LABEL_ROLE: "chroma"},
        restart_policy={"Name": "unless-stopped"},
    )
    client.containers.run(
        "searxng/searxng:latest",
        name=ODYSSEUS_SEARXNG,
        detach=True,
        network=ODYSSEUS_NETWORK,
        volumes={f"cc-{ODYSSEUS_SLUG}-searxng": {"bind": "/etc/searxng", "mode": "rw"}},
        labels={**labels, DOCKER_LABEL_ROLE: "searxng"},
        restart_policy={"Name": "unless-stopped"},
    )
    client.containers.run(
        "binwiederhier/ntfy:latest",
        name=ODYSSEUS_NTFY,
        detach=True,
        network=ODYSSEUS_NETWORK,
        command=["serve"],
        volumes={f"cc-{ODYSSEUS_SLUG}-ntfy": {"bind": "/var/lib/ntfy", "mode": "rw"}},
        labels={**labels, DOCKER_LABEL_ROLE: "ntfy"},
        restart_policy={"Name": "unless-stopped"},
    )

    host_port = pick_host_port(client, int(spec.get("host_port_hint") or 7000))
    client.containers.run(
        image,
        name=f"cc-{ODYSSEUS_SLUG}",
        detach=True,
        network=ODYSSEUS_NETWORK,
        ports={"7000/tcp": host_port},
        extra_hosts=HOST_GATEWAY,
        volumes={f"cc-{ODYSSEUS_SLUG}-0": {"bind": "/data", "mode": "rw"}},
        environment={
            "AUTH_ENABLED": "true",
            "APP_BIND": "0.0.0.0",
            "APP_PORT": "7000",
            "CHROMA_HOST": ODYSSEUS_CHROMA,
            "CHROMA_PORT": "8000",
            "SEARXNG_BASE_URL": f"http://{ODYSSEUS_SEARXNG}:8080",
            "NTFY_BASE_URL": f"http://{ODYSSEUS_NTFY}",
            "OLLAMA_BASE_URL": "http://host.docker.internal:11434/v1",
        },
        labels=labels,
        restart_policy={"Name": "unless-stopped"},
    )

    installed_version = _image_version(client, image)
    InstalledService.objects.filter(slug=ODYSSEUS_SLUG).update(
        host_port=host_port,
        installed_version=installed_version,
        status=InstalledService.Status.RUNNING,
        error="",
    )
    create_dashboard_card(ODYSSEUS_SLUG, entry, host_port)


def _securo_backend_env(db_password, secret_key, frontend_url, mcp_secret):
    return {
        "DATABASE_URL": f"postgresql+asyncpg://securo:{db_password}@{SECURO_DB}:5432/securo",
        "SECRET_KEY": secret_key,
        "DEBUG": "false",
        "FRONTEND_URL": frontend_url,
        "REDIS_URL": f"redis://{SECURO_REDIS}:6379/0",
        "STORAGE_LOCAL_PATH": "/app/data/attachments",
        "AGENTS_KNOWLEDGE_STORAGE_PATH": "/app/data/agent_knowledge",
        "AGENTS_ENABLED": "false",
        "LOCAL_AUTH_ENABLED": "true",
        "TRUSTED_PROXY_HOPS": "1",
        "AGENTS_OLLAMA_BASE_URL": "http://host.docker.internal:11434",
        "AGENTS_MCP_JWT_SECRET": mcp_secret,
    }


def _securo_backend_volumes():
    return {
        SECURO_ATTACHMENTS_VOLUME: {"bind": "/app/data/attachments", "mode": "rw"},
        SECURO_KNOWLEDGE_VOLUME: {"bind": "/app/data/agent_knowledge", "mode": "rw"},
        SECURO_EMBEDDINGS_VOLUME: {"bind": "/app/data/embedding_models", "mode": "rw"},
    }


def _run_securo_backend(client, labels, env, role, name, command):
    return client.containers.run(
        SECURO_BACKEND_IMAGE,
        name=name,
        detach=True,
        network=SECURO_NETWORK,
        extra_hosts=HOST_GATEWAY,
        volumes=_securo_backend_volumes(),
        environment=env,
        command=command,
        labels={**labels, DOCKER_LABEL_ROLE: role},
        restart_policy={"Name": "unless-stopped"},
    )


def _install_securo(client, entry, spec):
    frontend_image = spec.get("image", "").strip() or SECURO_FRONTEND_IMAGE
    client.images.pull(frontend_image)
    client.images.pull(SECURO_BACKEND_IMAGE)
    client.images.pull(SECURO_DB_IMAGE)
    client.images.pull(SECURO_REDIS_IMAGE)

    db_password = _previous_container_env(client, SECURO_DB, "POSTGRES_PASSWORD")
    secret_key = _previous_container_env(client, SECURO_BACKEND, "SECRET_KEY")
    mcp_secret = _previous_container_env(client, SECURO_BACKEND, "AGENTS_MCP_JWT_SECRET")
    if not db_password:
        db_password = secrets.token_urlsafe(32)
    if not secret_key:
        secret_key = secrets.token_urlsafe(48)
    if not mcp_secret:
        mcp_secret = secrets.token_urlsafe(32)

    _remove_labeled_containers(client, SECURO_SLUG)
    _remove_container(client, f"cc-{SECURO_SLUG}")
    for name in SECURO_SIDECARS:
        _remove_container(client, name)

    labels = {DOCKER_LABEL_SLUG: SECURO_SLUG}
    _ensure_network(client, SECURO_NETWORK, labels)
    for volume in (
        SECURO_DB_VOLUME,
        SECURO_ATTACHMENTS_VOLUME,
        SECURO_KNOWLEDGE_VOLUME,
        SECURO_EMBEDDINGS_VOLUME,
    ):
        _ensure_volume(client, volume, labels)

    db_container = client.containers.run(
        SECURO_DB_IMAGE,
        name=SECURO_DB,
        detach=True,
        network=SECURO_NETWORK,
        volumes={SECURO_DB_VOLUME: {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
        environment={
            "POSTGRES_USER": "securo",
            "POSTGRES_PASSWORD": db_password,
            "POSTGRES_DB": "securo",
        },
        labels={**labels, DOCKER_LABEL_ROLE: "db"},
        restart_policy={"Name": "unless-stopped"},
    )
    redis_container = client.containers.run(
        SECURO_REDIS_IMAGE,
        name=SECURO_REDIS,
        detach=True,
        network=SECURO_NETWORK,
        labels={**labels, DOCKER_LABEL_ROLE: "redis"},
        restart_policy={"Name": "unless-stopped"},
    )
    _wait_for_postgres(db_container, user="securo", database="securo")
    _wait_for_redis(redis_container)

    host_port = pick_host_port(client, int(spec.get("host_port_hint") or 3030))
    host = services_host()
    frontend_url = f"http://{host}:{host_port}"
    backend_env = _securo_backend_env(db_password, secret_key, frontend_url, mcp_secret)

    _run_securo_backend(
        client,
        labels,
        backend_env,
        "backend",
        SECURO_BACKEND,
        'sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"',
    )
    _run_securo_backend(
        client,
        labels,
        backend_env,
        "worker",
        SECURO_WORKER,
        "celery -A app.worker worker --loglevel=info --concurrency=2",
    )
    _run_securo_backend(
        client,
        labels,
        backend_env,
        "beat",
        SECURO_BEAT,
        "celery -A app.worker beat --loglevel=info",
    )
    client.containers.run(
        frontend_image,
        name=f"cc-{SECURO_SLUG}",
        detach=True,
        network=SECURO_NETWORK,
        ports={"8080/tcp": host_port},
        environment={
            "BACKEND_URL": f"http://{SECURO_BACKEND}:8000",
            "FRONTEND_URL": frontend_url,
        },
        labels=labels,
        restart_policy={"Name": "unless-stopped"},
    )

    installed_version = _image_version(client, frontend_image)
    InstalledService.objects.filter(slug=SECURO_SLUG).update(
        host_port=host_port,
        installed_version=installed_version,
        status=InstalledService.Status.RUNNING,
        error="",
    )
    create_dashboard_card(SECURO_SLUG, entry, host_port)


def create_dashboard_card(slug, entry, host_port):
    host = services_host()
    category_name = entry.get("category", "Services")
    category, _ = ServiceCategory.objects.get_or_create(
        name=category_name,
        defaults={"sort_order": 99},
    )
    Service.objects.filter(catalog_slug=slug).delete()
    if slug == "uptime-kuma":
        Service.objects.filter(name__iexact=entry["name"]).delete()
    widget_type = entry.get("widget_type", "none")
    service = Service(
        category=category,
        name=entry["name"],
        description=LIBRARY_DESCRIPTIONS.get(slug) or entry.get("tagline", ""),
        host=host,
        port=host_port,
        path=entry.get("path", "/") or "/",
        icon=icon_url_for_entry(slug, entry.get("icon", ""), name=entry.get("name", "")),
        catalog_slug=slug,
        widget_type=widget_type,
        is_public=False,
        is_misc=False,
        enabled=True,
    )
    if widget_type != "none":
        service.widget_url = f"http://{host}:{host_port}"
    service.save()
    if widget_type == "pihole":
        apply_preset_metrics(service, "pihole")
    elif widget_type == "speedtest":
        apply_preset_metrics(service, "speedtest")
    try:
        from dashboard.services import probe_service_health

        probe_service_health(service)
    except Exception:
        logger.debug("Initial health probe failed for %s", slug)
    return service


def delete_dashboard_card(slug):
    rows = list(Service.objects.filter(catalog_slug=slug))
    if slug != "uptime-kuma":
        try:
            from dashboard.kuma import delete_monitors_for_services

            delete_monitors_for_services(rows)
        except Exception:
            logger.debug("Could not remove Kuma monitors for %s", slug)
    Service.objects.filter(catalog_slug=slug).delete()


def _install_worker(slug, install_options=None):
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
        if slug == NEXTCLOUD_SLUG:
            _install_nextcloud(client, entry, spec, install_options or {})
            return
        if slug == BOOKSTACK_SLUG:
            _install_bookstack(client, entry, spec)
            return
        if slug == ODYSSEUS_SLUG:
            _install_odysseus(client, entry, spec)
            return
        if slug == SECURO_SLUG:
            _install_securo(client, entry, spec)
            return
        client.images.pull(image)
        _remove_container(client, container_name)

        if slug == TUNNEL_SLUG:
            installed_version = _image_version(client, image)
            InstalledService.objects.filter(slug=slug).update(
                host_port=0,
                installed_version=installed_version,
                status=InstalledService.Status.STOPPED,
                error="",
            )
            return

        host_port = pick_host_port(client, start_port)

        volume_paths = list(spec.get("volumes") or [])
        env = dict(spec.get("env") or {})
        pihole_password = ""
        if slug == "pihole":
            from . import pihole as pihole_setup

            volume_paths = pihole_setup.ensure_volume_paths(volume_paths)
            pihole_password = secrets.token_urlsafe(18)
            env = pihole_setup.apply_env(env, pihole_password)

        volume_map = {}
        for idx, container_path in enumerate(volume_paths):
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

        run_kwargs = {
            "name": container_name,
            "detach": True,
            "ports": ports,
            "volumes": volume_map or None,
            "environment": env or None,
            "labels": {DOCKER_LABEL_SLUG: slug},
            "restart_policy": {"Name": "unless-stopped"},
        }
        if spec.get("pid_mode"):
            run_kwargs["pid_mode"] = spec["pid_mode"]
        extra_hosts = spec.get("extra_hosts") or {}
        if extra_hosts:
            run_kwargs["extra_hosts"] = extra_hosts
        client.containers.run(image, **run_kwargs)

        installed_version = _image_version(client, image)
        InstalledService.objects.filter(slug=slug).update(
            host_port=host_port,
            installed_version=installed_version,
            status=InstalledService.Status.RUNNING,
            error="",
        )
        if slug not in NO_CARD_ON_INSTALL:
            service = create_dashboard_card(slug, entry, host_port)
            if slug == "pihole" and pihole_password:
                from . import pihole as pihole_setup

                extra_user = None
                user_id = (install_options or {}).get("user_id")
                if user_id:
                    from django.contrib.auth.models import User

                    extra_user = User.objects.filter(pk=user_id).first()
                pihole_setup.persist_credentials(
                    service, pihole_password, extra_user=extra_user
                )
        _clear_uptime_cache_if_kuma(slug)
    except Exception as exc:  # noqa: BLE001 - background worker must record failure
        logger.exception("Install failed for %s", slug)
        InstalledService.objects.filter(slug=slug).update(
            status=InstalledService.Status.ERROR,
            error=str(exc)[:500],
        )


def start_install(slug, request=None, install_options=None):
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

    detect_services_host(request)

    options = dict(install_options or {})
    if request is not None and getattr(request.user, "pk", None):
        options["user_id"] = request.user.pk

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
    _clear_uptime_cache_if_kuma(slug)
    thread = threading.Thread(
        target=_install_worker,
        args=(slug, options),
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
        if slug == NEXTCLOUD_SLUG:
            _remove_container(client, NEXTCLOUD_DB_CONTAINER)
        elif slug == BOOKSTACK_SLUG:
            _remove_container(client, BOOKSTACK_DB_CONTAINER)
        elif slug == ODYSSEUS_SLUG:
            _remove_labeled_containers(client, ODYSSEUS_SLUG)
            for name in ODYSSEUS_SIDECARS:
                _remove_container(client, name)
        elif slug == SECURO_SLUG:
            _remove_labeled_containers(client, SECURO_SLUG)
            for name in SECURO_SIDECARS:
                _remove_container(client, name)
        _remove_service_volumes(
            client,
            slug,
            remove_data,
            extra_volume_names=extra_volumes,
        )
        if slug == NEXTCLOUD_SLUG:
            _remove_network(client, NEXTCLOUD_NETWORK)
        elif slug == BOOKSTACK_SLUG:
            _remove_network(client, BOOKSTACK_NETWORK)
        elif slug == ODYSSEUS_SLUG:
            _remove_network(client, ODYSSEUS_NETWORK)
        elif slug == SECURO_SLUG:
            _remove_network(client, SECURO_NETWORK)
    except docker.errors.DockerException as exc:
        logger.warning("Docker uninstall issue for %s: %s", slug, exc)
        InstalledService.objects.filter(slug=slug).update(
            status=InstalledService.Status.ERROR,
            error=str(exc)[:500],
        )
        return False, str(exc)

    if slug == TUNNEL_SLUG:
        try:
            from library.cloudflare import unlink_account

            unlink_account(delete_remote=False)
        except Exception:
            logger.debug("Could not unlink Cloudflare on uninstall")
    delete_dashboard_card(slug)
    InstalledService.objects.filter(slug=slug).delete()
    _clear_uptime_cache_if_kuma(slug)
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
