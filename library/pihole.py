"""Pi-hole install credentials, vault sync, and browser auto-login helpers."""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlparse

import docker
from django.contrib.auth.models import User
from django.urls import reverse

from core import vault as vault_api

logger = logging.getLogger(__name__)

SLUG = "pihole"
VAULT_LABEL = "Pi-hole"
CONTAINER_NAME = "cc-pihole"
CONFIG_PATH = "/etc/pihole"


def generate_password() -> str:
    return secrets.token_urlsafe(18)


def supports_autologin(service) -> bool:
    return (getattr(service, "catalog_slug", "") or "") == SLUG or getattr(
        service, "widget_type", ""
    ) == "pihole"


def apply_env(env, password: str) -> dict:
    merged = dict(env or {})
    merged["FTLCONF_webserver_api_password"] = password
    merged["FTLCONF_webserver_api_enabled"] = "true"
    merged["FTLCONF_dns_listeningMode"] = "all"
    return merged


def ensure_volume_paths(paths) -> list:
    out = list(paths or [])
    if CONFIG_PATH not in out:
        out.append(CONFIG_PATH)
    return out


def persist_credentials(service, password: str, extra_user=None):
    service.widget_api_key = password
    service.save(update_fields=["widget_api_key"])
    users = list(User.objects.filter(is_superuser=True, is_active=True))
    if extra_user is not None and extra_user not in users:
        users.append(extra_user)
    notes = "Set automatically when Pi-hole was installed. Used to open the admin UI."
    for user in users:
        vault_api.upsert_for_service(
            user,
            service,
            label=VAULT_LABEL,
            username="",
            secret=password,
            notes=notes,
        )


def password_for(user, service) -> str:
    if user is not None and getattr(user, "is_authenticated", False):
        creds = vault_api.get_credentials(user, service)
        if creds and creds.secret:
            return creds.secret
    return (service.widget_api_key or "").strip()


def set_container_password(password: str) -> bool:
    if not password:
        return False
    try:
        from .installer import get_docker_client

        client = get_docker_client()
        container = client.containers.get(CONTAINER_NAME)
        commands = (
            ["pihole", "setpassword", password],
            ["pihole-FTL", "--config", "webserver.api.password", password],
        )
        last_output = b""
        for command in commands:
            result = container.exec_run(command)
            if getattr(result, "exit_code", 1) == 0:
                return True
            last_output = getattr(result, "output", b"") or b""
        logger.warning("pihole setpassword failed: %s", last_output[:200])
        return False
    except docker.errors.NotFound:
        logger.warning("Pi-hole container %s not found", CONTAINER_NAME)
        return False
    except docker.errors.DockerException as exc:
        logger.warning("Could not set Pi-hole password: %s", exc)
        return False


def ensure_password(service, user=None) -> str:
    password = password_for(user, service)
    if password:
        if user is not None and getattr(user, "is_authenticated", False):
            creds = vault_api.get_credentials(user, service)
            if not creds or not creds.secret:
                persist_credentials(service, password, extra_user=user)
            elif not service.widget_api_key:
                service.widget_api_key = password
                service.save(update_fields=["widget_api_key"])
        return password
    password = generate_password()
    if not set_container_password(password):
        return ""
    persist_credentials(service, password, extra_user=user)
    return password


def auth_base(service) -> str:
    url = (service.widget_url or service.build_href() or "").strip()
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path or ""
    if path.rstrip("/").endswith("/admin"):
        path = path[: path.lower().rfind("/admin")]
    return f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")


def browser_url(request, service) -> str:
    host = (request.get_host() or "").split(":")[0].strip("[]")
    path = service.path or "/admin/"
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    port = service.port
    scheme = "https" if request.is_secure() and port == 443 else "http"
    if port and port not in (80, 443):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    return f"{scheme}://{netloc}{path}"


def launch_path(service) -> str:
    return reverse("service_launch", args=[service.id])


def attach_launch_href(request, service):
    open_href = getattr(service, "open_href", "") or service.build_href()
    if request.user.is_authenticated and supports_autologin(service):
        service.launch_href = launch_path(service)
    else:
        service.launch_href = open_href
    return service
