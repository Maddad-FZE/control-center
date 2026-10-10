"""Live Docker address inspection and card URL reconciliation.

Never call Service.save() without update_fields — save() always resets widget_url.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

from django.core.cache import cache
from django.db import transaction

from dashboard.models import Service
from library.catalog import get_docker_spec, get_service_by_slug
from library.detect import _host_port_from_container
from library.installer import (
    DOCKER_LABEL_ROLE,
    DOCKER_LABEL_SLUG,
    get_docker_client,
    services_host,
)
from library.models import InstalledService, TunnelRoute

logger = logging.getLogger(__name__)

PROTECTED_CONTAINERS = frozenset({"control-center", "control-center-tick"})


@dataclass
class AddressSnapshot:
    source: str = "card"
    host: str = ""
    port: int | None = None
    path: str = "/"
    scheme: str = "http"
    bindings: list[dict] = field(default_factory=list)
    conflict: str = ""
    confidence: str = "low"
    container_name: str = ""
    container_status: str = ""
    installed_port: int | None = None
    docker_available: bool = True
    docker_error: str = ""


@dataclass
class SyncResult:
    ok: bool
    changed: dict
    previous: dict
    message: str
    cache_bust: bool = False
    partial: list[str] = field(default_factory=list)


def _parse_url(url):
    parsed = urlparse((url or "").strip())
    return parsed


def _port_from_parsed(parsed):
    if parsed.port:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return None


def _auto_derived_urls(host, port, path="/"):
    if not host or not port:
        return set()
    base = f"http://{host}:{int(port)}"
    path = path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return {
        base,
        f"{base}/",
        f"{base}{path}",
        f"{base}/admin/",
        f"{base}/admin",
    }


def is_auto_derived(url, host, port, path="/"):
    if not url:
        return True
    candidates = _auto_derived_urls(host, port, path)
    stripped = (url or "").rstrip("/")
    if url in candidates or stripped in candidates:
        return True
    parsed = _parse_url(url)
    if (parsed.hostname or "") == host and _port_from_parsed(parsed) == int(port):
        return True
    return False


def replace_netloc(url, new_host, new_port, scheme="http"):
    parsed = _parse_url(url)
    if not parsed.scheme and not parsed.netloc:
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = "/" + path
        return f"{scheme}://{new_host}:{int(new_port)}{path}"
    netloc = f"{new_host}:{int(new_port)}"
    new_scheme = parsed.scheme or scheme
    return urlunparse(
        (new_scheme, netloc, parsed.path or "/", parsed.params, parsed.query, parsed.fragment)
    )


def rewrite_if_auto(url, old_host, old_port, new_host, new_port, path="/"):
    if not url:
        return url, False
    if is_auto_derived(url, old_host, old_port, path):
        return replace_netloc(url, new_host, new_port), True
    return url, False


def _tcp_bindings(container):
    ports = (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
    rows = []
    for key, bindings in ports.items():
        if not key.endswith("/tcp") or not bindings:
            continue
        container_port = key.split("/", 1)[0]
        for binding in bindings:
            host_port = binding.get("HostPort")
            if not host_port:
                continue
            rows.append(
                {
                    "container_port": int(container_port),
                    "host_port": int(host_port),
                    "proto": "tcp",
                }
            )
    return rows


def pick_binding(bindings, preferred_container_port=None):
    if not bindings:
        return None, "missing_container"
    by_container = {}
    for row in bindings:
        by_container.setdefault(row["container_port"], set()).add(row["host_port"])
    if preferred_container_port and preferred_container_port in by_container:
        hosts = sorted(by_container[preferred_container_port])
        if len(hosts) == 1:
            return hosts[0], ""
        return None, "multiple_bindings"
    hosts = sorted({row["host_port"] for row in bindings})
    if len(hosts) == 1:
        return hosts[0], ""
    if not hosts:
        return None, "missing_container"
    return None, "multiple_bindings"


def _preferred_container_port(slug):
    entry = get_service_by_slug(slug) if slug else None
    if not entry:
        return None
    spec = get_docker_spec(entry)
    port = spec.get("container_port") or entry.get("default_port")
    try:
        return int(port) if port else None
    except (TypeError, ValueError):
        return None


def _find_container(client, service, inst):
    names = []
    if inst and inst.container_name:
        names.append(inst.container_name.lstrip("/"))
    slug = (service.catalog_slug or "").strip()
    if slug:
        names.append(f"cc-{slug}")
    for name in names:
        try:
            return client.containers.get(name)
        except Exception:
            continue
    if not slug:
        return None
    try:
        labeled = client.containers.list(
            all=True, filters={"label": f"{DOCKER_LABEL_SLUG}={slug}"}
        )
    except Exception:
        return None
    if not labeled:
        return None
    preferred = _preferred_container_port(slug)
    frontend = []
    for container in labeled:
        labels = (container.attrs.get("Config") or {}).get("Labels") or {}
        role = (labels.get(DOCKER_LABEL_ROLE) or "").strip().lower()
        if role in ("", "frontend", "app"):
            frontend.append(container)
    pool = frontend or labeled
    if preferred:
        for container in pool:
            bindings = _tcp_bindings(container)
            if any(row["container_port"] == preferred for row in bindings):
                return container
    if len(pool) == 1:
        return pool[0]
    return None


def inspect_live_address(service: Service) -> AddressSnapshot:
    snap = AddressSnapshot()
    snap.path = service.path or "/"
    parsed = _parse_url(service.href or service.widget_url or "")
    snap.scheme = parsed.scheme or "http"
    inst = None
    slug = (service.catalog_slug or "").strip()
    if slug:
        inst = InstalledService.objects.filter(slug=slug).first()
    if inst:
        snap.installed_port = inst.host_port or None
        snap.container_name = inst.container_name or ""

    if slug:
        snap.host = services_host() or service.host or ""
    else:
        snap.host = service.host or parsed.hostname or ""
        snap.port = service.port or _port_from_parsed(parsed)
        snap.source = "card"
        snap.confidence = "card"
        return snap

    if not slug:
        return snap

    try:
        client = get_docker_client()
        container = _find_container(client, service, inst)
    except Exception as exc:
        snap.docker_available = False
        snap.docker_error = str(exc)[:200]
        snap.source = "installed" if snap.installed_port else "card"
        snap.port = snap.installed_port or service.port
        snap.confidence = "stale_if_no_docker"
        snap.conflict = "docker_down"
        return snap

    if container is None:
        snap.conflict = "missing_container"
        snap.source = "installed" if snap.installed_port else "card"
        snap.port = snap.installed_port or service.port
        snap.confidence = "low"
        return snap

    snap.container_name = container.name.lstrip("/")
    snap.container_status = (container.attrs.get("State") or {}).get("Status") or container.status
    snap.bindings = _tcp_bindings(container)
    preferred = _preferred_container_port(slug)
    live_port, conflict = pick_binding(snap.bindings, preferred)
    if conflict and live_port is None:
        live_port = _host_port_from_container(container, preferred) or None
        if live_port and conflict == "missing_container":
            conflict = ""
        elif conflict == "multiple_bindings":
            live_port = None
    snap.conflict = conflict
    snap.port = live_port
    snap.source = "docker"
    snap.confidence = "high" if live_port and not conflict else "low"
    if not snap.host:
        snap.host = service.host or services_host()
    return snap


def diff_addresses(service: Service, snap: AddressSnapshot) -> list[dict]:
    findings = []
    slug = (service.catalog_slug or "").strip()
    if not slug:
        return findings
    if snap.conflict == "docker_down":
        findings.append(
            {
                "issue_id": "ISSUE_DOCKER_UNAVAILABLE",
                "severity": "high",
                "confidence": 0.8,
                "plain_language": "Control Center cannot talk to Docker, so it cannot confirm the live port.",
            }
        )
        return findings
    if snap.conflict == "multiple_bindings":
        findings.append(
            {
                "issue_id": "ISSUE_MULTIPLE_BINDINGS",
                "severity": "medium",
                "confidence": 0.9,
                "plain_language": "This container publishes more than one host port. Control Center will not guess which one the card should use.",
            }
        )
        return findings
    if snap.conflict == "missing_container":
        findings.append(
            {
                "issue_id": "ISSUE_CONTAINER_MISSING",
                "severity": "high",
                "confidence": 0.85,
                "plain_language": "The Docker container for this card was not found.",
            }
        )
        return findings
    if snap.port and service.port and int(snap.port) != int(service.port):
        findings.append(
            {
                "issue_id": "ISSUE_PORT_CARD_DRIFT",
                "severity": "high",
                "confidence": 0.91,
                "plain_language": (
                    f"{service.name} is listening on port {snap.port}, "
                    f"but this card still points at {service.port}."
                ),
            }
        )
    inst_port = snap.installed_port
    if snap.port and inst_port and int(snap.port) != int(inst_port) and inst_port != 0:
        findings.append(
            {
                "issue_id": "ISSUE_PORT_INSTALLED_DRIFT",
                "severity": "medium",
                "confidence": 0.9,
                "plain_language": "The Library record still has the old port. Docker has already moved.",
            }
        )
    lan = services_host()
    if lan and service.host and service.host != lan and slug:
        findings.append(
            {
                "issue_id": "ISSUE_HOST_STALE",
                "severity": "medium",
                "confidence": 0.7,
                "plain_language": (
                    f"This card still uses host {service.host}, but Control Center "
                    f"now publishes library apps on {lan}."
                ),
            }
        )
    if snap.port and snap.host:
        expected_href = f"http://{snap.host}:{int(snap.port)}{(service.path or '/')}"
        if service.href and not is_auto_derived(
            service.href, service.host, service.port or 0, service.path
        ):
            pass
        elif service.href and service.port and snap.port != service.port:
            findings.append(
                {
                    "issue_id": "ISSUE_HREF_DESYNC",
                    "severity": "medium",
                    "confidence": 0.8,
                    "plain_language": "The open link on this card does not match the live address.",
                }
            )
        _ = expected_href
    return findings


def invalidate_service_caches(service: Service, old_urls: list[str] | None = None) -> None:
    cache.delete("health:results")
    cache.delete("uptime:payload")
    cache.delete("alerts:recent")
    cache.delete("docker:containers")
    cache.delete("widgets:bundle:False")
    cache.delete("widgets:bundle:True")
    urls = list(old_urls or [])
    for candidate in (service.href, service.widget_url, service.health_check_url):
        if candidate:
            urls.append(candidate)
    for url in {item.rstrip("/") for item in urls if item}:
        for kind in ("none", "pihole", "speedtest", "generic"):
            cache.delete(f"widget:{kind}:{url}:")
            if service.widget_api_key:
                cache.delete(f"widget:{kind}:{url}:{service.widget_api_key}")
        if service.widget_api_key:
            digest_key = f"pihole:sid:{url.rstrip('/')}:"
            for key in cache.keys(f"{digest_key}*") if hasattr(cache, "keys") else []:
                cache.delete(key)


def apply_address_sync(
    service: Service,
    snap: AddressSnapshot,
    *,
    preserve_custom_urls: bool = True,
    update_tunnel: bool = True,
    update_kuma: bool = True,
    update_host: bool = False,
    actor=None,
) -> SyncResult:
    if snap.conflict in ("multiple_bindings", "missing_container"):
        return SyncResult(
            ok=False,
            changed={},
            previous={},
            message="Cannot sync while the live port is unclear.",
        )
    new_port = snap.port
    new_host = snap.host or service.host
    if update_host:
        new_host = services_host() or new_host
    if not new_host or not new_port:
        return SyncResult(ok=False, changed={}, previous={}, message="No live address to apply.")

    old_host = service.host
    old_port = service.port
    previous = {
        "host": service.host,
        "port": service.port,
        "href": service.href,
        "health_check_url": service.health_check_url,
        "widget_url": service.widget_url,
        "path": service.path,
        "installed_port": snap.installed_port,
    }
    path = service.path or "/"
    href = service.href
    health = service.health_check_url
    widget = service.widget_url
    href_changed = health_changed = widget_changed = False
    if preserve_custom_urls:
        href, href_changed = rewrite_if_auto(href, old_host, old_port, new_host, new_port, path)
        health, health_changed = rewrite_if_auto(
            health, old_host, old_port, new_host, new_port, path
        )
        widget, widget_changed = rewrite_if_auto(
            widget, old_host, old_port, new_host, new_port, path
        )
    else:
        href = f"http://{new_host}:{int(new_port)}{path}"
        health = href
        widget = f"http://{new_host}:{int(new_port)}"
        href_changed = health_changed = widget_changed = True
    if not href:
        href = f"http://{new_host}:{int(new_port)}{path}"
        href_changed = True

    update_fields = []
    if service.host != new_host:
        service.host = new_host
        update_fields.append("host")
    if service.port != int(new_port):
        service.port = int(new_port)
        update_fields.append("port")
    if href_changed and service.href != href:
        service.href = href
        update_fields.append("href")
    if health_changed and service.health_check_url != health:
        service.health_check_url = health
        update_fields.append("health_check_url")
    if widget_changed and service.widget_url != widget:
        service.widget_url = widget
        update_fields.append("widget_url")

    slug = (service.catalog_slug or "").strip()
    with transaction.atomic():
        if update_fields:
            # QuerySet.update skips Service.save(), which always rewrites widget_url.
            Service.objects.filter(pk=service.pk).update(
                **{field: getattr(service, field) for field in update_fields}
            )
        if slug:
            InstalledService.objects.filter(slug=slug).exclude(host_port=0).update(
                host_port=int(new_port)
            )
            if snap.installed_port in (None, 0):
                InstalledService.objects.filter(slug=slug).update(host_port=int(new_port))

    partial = []
    if update_kuma:
        try:
            from dashboard.kuma import connect_kuma, kuma_is_present, sync_monitors

            if kuma_is_present() and slug != "uptime-kuma":
                api = connect_kuma()
                if api is not None:
                    try:
                        sync_monitors(api)
                    finally:
                        if hasattr(api, "disconnect"):
                            api.disconnect()
        except Exception as exc:
            logger.debug("Kuma sync after address apply failed: %s", exc)
            partial.append("kuma")

    if update_tunnel and slug:
        try:
            from core.models import SiteSettings
            from library import cloudflare as cf

            route = TunnelRoute.objects.filter(service_id=service.id).first()
            if route is None:
                route = TunnelRoute.objects.filter(catalog_slug=slug).first()
            if route is not None:
                origin = cf.origin_for_service(service, catalog_slug=slug, host_port=int(new_port))
                if origin and origin != route.origin_url:
                    route.origin_url = origin
                    route.save(update_fields=["origin_url"])
                    if cf.tunnel_is_linked():
                        cf._sync_ingress(SiteSettings.load(), list(TunnelRoute.objects.order_by("hostname")))
        except Exception as exc:
            logger.debug("Tunnel sync after address apply failed: %s", exc)
            partial.append("tunnel")

    invalidate_service_caches(
        service, [previous.get("href"), previous.get("widget_url"), previous.get("health_check_url")]
    )
    changed = {field: getattr(service, field) for field in update_fields}
    if slug:
        changed["installed_port"] = int(new_port)
    message = "Card address updated."
    if partial:
        message = "Card address updated, but some linked systems still need a retry."
    return SyncResult(
        ok=True,
        changed=changed,
        previous=previous,
        message=message,
        cache_bust=True,
        partial=partial,
    )


def allowed_container_name(name):
    from dashboard.hostops import CONTAINER_NAME_RE

    name = (name or "").strip().lstrip("/")
    if not CONTAINER_NAME_RE.match(name):
        return False
    if name in PROTECTED_CONTAINERS:
        return False
    return True
