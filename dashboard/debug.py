"""Card-level Debug diagnosis pipeline."""

from __future__ import annotations

import logging
import socket
import ssl
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import docker
import requests
from django.core.cache import cache
from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone

from core.models import log_audit
from core.version import get_current_version
from dashboard.debug_report import redact_mapping, redact_text, redact_url, sanitize_log_lines
from dashboard.models import DebugIncident, Service, ServiceCheck
from library.debug_ports import AddressSnapshot, diff_addresses, inspect_live_address
from library.installer import (
    DOCKER_LABEL_SLUG,
    get_docker_client,
    services_host,
    stack_restart_order,
)
from library.models import InstalledService, TunnelRoute

logger = logging.getLogger(__name__)

BUDGET_S = 20
DIAG_LOCK_TTL = 60
RATE_LIMIT = 10
RATE_WINDOW = 300
GLOBAL_CONCURRENCY = 3
PROTECTED = frozenset({"control-center", "control-center-tick"})

ACTION_META = {
    "ACTION_RECHECK": {"title": "Check again", "risk": "safe", "confirm": False},
    "ACTION_DISCOVER_PORT": {"title": "Find the current port", "risk": "safe", "confirm": False},
    "ACTION_SYNC_CARD_PORT": {
        "title": "Update this card to the current port",
        "risk": "safe",
        "confirm": False,
    },
    "ACTION_UPDATE_LINKED_URLS": {
        "title": "Update health, widgets, and public links",
        "risk": "safe",
        "confirm": False,
    },
    "ACTION_REFRESH_HOST": {
        "title": "Use this server’s current address",
        "risk": "safe",
        "confirm": True,
        "confirmation_language": "Update this card to the current LAN address?",
    },
    "ACTION_CLEAR_CACHES": {"title": "Clear cached status", "risk": "safe", "confirm": False},
    "ACTION_RESYNC_KUMA": {"title": "Refresh Uptime Kuma", "risk": "safe", "confirm": False},
    "ACTION_REPAIR_TUNNEL_ORIGIN": {
        "title": "Fix the public address",
        "risk": "disruptive",
        "confirm": True,
        "confirmation_language": "Update the public tunnel origin for this service?",
    },
    "ACTION_START": {
        "title": "Start service",
        "risk": "disruptive",
        "confirm": True,
        "confirmation_language": "Start this service?",
    },
    "ACTION_UNPAUSE": {
        "title": "Unpause service",
        "risk": "disruptive",
        "confirm": True,
        "confirmation_language": "Unpause this service?",
    },
    "ACTION_RESTART": {
        "title": "Restart service",
        "risk": "disruptive",
        "confirm": True,
        "confirmation_language": "Restart this service? It will be briefly offline.",
    },
    "ACTION_RESTART_STACK": {
        "title": "Restart full stack",
        "risk": "disruptive",
        "confirm": True,
        "confirmation_language": "Restart this app and its supporting containers? Volumes stay.",
    },
    "ACTION_RESTORE_RESTART_POLICY": {
        "title": "Make it restart after a crash",
        "risk": "safe",
        "confirm": False,
    },
    "ACTION_RESTART_TICK": {
        "title": "Restart health tick",
        "risk": "disruptive",
        "confirm": True,
        "confirmation_language": "Restart the Control Center health checker?",
    },
    "ACTION_RESTART_KUMA": {
        "title": "Restart Uptime Kuma",
        "risk": "disruptive",
        "confirm": True,
        "confirmation_language": "Restart Uptime Kuma? Health history stays.",
    },
    "ACTION_RESTART_CF": {
        "title": "Restart Cloudflare connector",
        "risk": "disruptive",
        "confirm": True,
        "confirmation_language": "Restart the Cloudflare tunnel connector?",
    },
    "ACTION_RETRY_INSTALL": {
        "title": "Retry failed install",
        "risk": "disruptive",
        "confirm": True,
        "confirmation_language": "Retry installing this library service? Existing named volumes stay.",
    },
    "ACTION_RECREATE_MANAGED": {
        "title": "Recreate the container (keep data)",
        "risk": "disruptive",
        "confirm": True,
        "confirmation_language": "Recreate this managed container while keeping its volumes?",
    },
    "ACTION_REGEN_ENV": {
        "title": "Update the app’s public URL",
        "risk": "disruptive",
        "confirm": True,
        "confirmation_language": "Recreate the container so APP_URL / trusted domains match the live port? Volumes stay.",
    },
    "ACTION_REBOOT_HOST": {
        "title": "Restart the server",
        "risk": "destructive",
        "confirm": True,
        "confirmation_language": "This reboots the whole machine. Every service will go offline until it comes back.",
    },
    "ACTION_OPEN_EDITOR": {"title": "Edit card", "risk": "safe", "confirm": False, "href": True},
    "ACTION_OPEN_LOGS": {"title": "Open logs", "risk": "safe", "confirm": False, "href": True},
    "ACTION_OPEN_CREDENTIALS": {"title": "Open credentials", "risk": "safe", "confirm": False, "href": True},
    "ACTION_OPEN_OVERLAY": {"title": "Open in overlay", "risk": "safe", "confirm": False, "href": True},
    "ACTION_OPEN_LIBRARY": {"title": "Open Library", "risk": "safe", "confirm": False, "href": True},
    "ACTION_OPEN_SETTINGS": {"title": "Open Settings", "risk": "safe", "confirm": False, "href": True},
}

FINDING_TITLES = {
    "ISSUE_PORT_CARD_DRIFT": "This card still uses the old port",
    "ISSUE_PORT_INSTALLED_DRIFT": "Library still has the old port",
    "ISSUE_HOST_STALE": "This card uses an old address",
    "ISSUE_HREF_DESYNC": "The open link is out of date",
    "ISSUE_DOCKER_UNAVAILABLE": "Cannot reach Docker",
    "ISSUE_MULTIPLE_BINDINGS": "This app has more than one port",
    "ISSUE_CONTAINER_MISSING": "The container was not found",
}

OPEN_HREFS = {
    "ACTION_OPEN_EDITOR": lambda service: reverse("service_edit", args=[service.id]),
    "ACTION_OPEN_LOGS": lambda service: reverse("settings") + "?section=logs",
    "ACTION_OPEN_CREDENTIALS": lambda service: reverse("profile") + f"?section=vault&service={service.id}",
    "ACTION_OPEN_OVERLAY": lambda service: reverse("service_view", args=[service.id]),
    "ACTION_OPEN_LIBRARY": lambda service: reverse("library"),
    "ACTION_OPEN_SETTINGS": lambda service: reverse("settings"),
}


def new_incident_id():
    return "dbg_" + uuid.uuid4().hex[:16]


def _probe_url(service):
    return (service.health_check_url or service.href or "").strip()


def _host_allowed(service, hostname):
    allowed = {
        (service.host or "").strip().lower(),
        (services_host() or "").strip().lower(),
    }
    parsed = urlparse(_probe_url(service))
    if parsed.hostname:
        allowed.add(parsed.hostname.lower())
    host = (hostname or "").strip().lower()
    return bool(host) and host in allowed


def _dns_probe(hostname, timeout=1.0):
    if not hostname:
        return {"ok": False, "error": "no hostname", "skipped": True}
    socket.setdefaulttimeout(timeout)
    try:
        infos = socket.getaddrinfo(hostname, None)
        addrs = sorted({item[4][0] for item in infos})
        return {"ok": True, "addresses": addrs, "error": ""}
    except Exception as exc:
        return {"ok": False, "addresses": [], "error": str(exc)[:200]}


def _tcp_probe(host, port, timeout=1.5):
    if not host or not port:
        return {"ok": False, "error": "missing host or port", "skipped": True}
    start = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            ms = int((time.perf_counter() - start) * 1000)
            return {"ok": True, "ms": ms, "error": ""}
    except ConnectionRefusedError as exc:
        return {"ok": False, "error": "connection refused", "detail": str(exc)[:120], "ms": int((time.perf_counter() - start) * 1000)}
    except socket.timeout:
        return {"ok": False, "error": "timeout", "ms": int((time.perf_counter() - start) * 1000)}
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:200], "ms": int((time.perf_counter() - start) * 1000)}


def _tls_probe(host, port, timeout=2.0):
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as sock:
                cert = sock.getpeercert()
                not_after = ""
                if cert:
                    not_after = cert.get("notAfter") or ""
                return {"ok": True, "not_after": not_after, "error": ""}
    except ssl.SSLCertVerificationError as exc:
        reason = "hostname" if "hostname" in str(exc).lower() else "untrusted"
        return {"ok": False, "error": str(exc)[:200], "reason": reason}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _http_probe(url, origin_host, timeout=8.0):
    if not url:
        return {"ok": False, "error": "no url", "skipped": True}
    parsed = urlparse(url)
    if parsed.hostname and origin_host and parsed.hostname.lower() != origin_host.lower():
        if not _host_allowed_host(origin_host, parsed.hostname):
            return {"ok": False, "error": "refusing to probe a different host", "ssrf_blocked": True}
    start = time.perf_counter()
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=False)
        if resp.status_code >= 400 or resp.status_code in (301, 302, 303, 307, 308):
            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location") or ""
                loc_host = urlparse(urljoin(url, location)).hostname
                if loc_host and loc_host.lower() != (parsed.hostname or "").lower():
                    return {
                        "ok": False,
                        "status": resp.status_code,
                        "error": "redirect left the original host",
                        "location": redact_url(location),
                        "ms": int((time.perf_counter() - start) * 1000),
                    }
            resp = requests.get(url, timeout=timeout, allow_redirects=True)
        ms = int((time.perf_counter() - start) * 1000)
        return {
            "ok": 200 <= resp.status_code < 400,
            "status": resp.status_code,
            "ms": ms,
            "error": "" if 200 <= resp.status_code < 400 else f"HTTP {resp.status_code}",
            "final_url": redact_url(resp.url),
            "x_frame_options": resp.headers.get("X-Frame-Options", ""),
        }
    except requests.exceptions.SSLError as exc:
        return {"ok": False, "error": str(exc)[:200], "tls": True, "ms": int((time.perf_counter() - start) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "ms": int((time.perf_counter() - start) * 1000)}


def _host_allowed_host(origin, other):
    return (origin or "").lower() == (other or "").lower()


def _docker_inspect(service):
    slug = (service.catalog_slug or "").strip()
    inst = InstalledService.objects.filter(slug=slug).first() if slug else None
    payload = {
        "available": False,
        "container": "",
        "status": "",
        "health": "",
        "oom_killed": False,
        "exit_code": None,
        "restart_policy": "",
        "restart_count": 0,
        "error": "",
        "sidecars": [],
        "managed": bool(inst.managed) if inst else False,
        "install_status": inst.status if inst else "",
        "install_error": (inst.error or "") if inst else "",
    }
    try:
        client = get_docker_client()
        client.ping()
        payload["available"] = True
    except Exception as exc:
        payload["error"] = str(exc)[:200]
        return payload
    name = (inst.container_name if inst else "") or (f"cc-{slug}" if slug else "")
    container = None
    if name:
        try:
            container = client.containers.get(name)
        except docker.errors.NotFound:
            payload["error"] = "not found"
        except Exception as exc:
            payload["error"] = str(exc)[:200]
    if container is not None:
        state = container.attrs.get("State") or {}
        host = container.attrs.get("HostConfig") or {}
        policy = host.get("RestartPolicy") or {}
        payload.update(
            {
                "container": container.name.lstrip("/"),
                "status": state.get("Status") or container.status,
                "health": ((state.get("Health") or {}).get("Status") or ""),
                "oom_killed": bool(state.get("OOMKilled")),
                "exit_code": state.get("ExitCode"),
                "restart_policy": policy.get("Name") or "",
                "restart_count": int(state.get("RestartCount") or 0),
                "error": "",
            }
        )
    if slug:
        try:
            labeled = client.containers.list(
                all=True, filters={"label": f"{DOCKER_LABEL_SLUG}={slug}"}
            )
        except Exception:
            labeled = []
        sidecars = []
        for item in labeled:
            item_name = item.name.lstrip("/")
            if payload["container"] and item_name == payload["container"]:
                continue
            item_state = item.attrs.get("State") or {}
            sidecars.append(
                {
                    "name": item_name,
                    "status": item_state.get("Status") or item.status,
                    "health": ((item_state.get("Health") or {}).get("Status") or ""),
                }
            )
        if not sidecars:
            for extra in stack_restart_order(slug):
                extra_name = extra.lstrip("/")
                if extra_name == payload.get("container"):
                    continue
                try:
                    extra_c = client.containers.get(extra_name)
                except Exception:
                    continue
                extra_state = extra_c.attrs.get("State") or {}
                sidecars.append(
                    {
                        "name": extra_name,
                        "status": extra_state.get("Status") or extra_c.status,
                        "health": ((extra_state.get("Health") or {}).get("Status") or ""),
                    }
                )
        payload["sidecars"] = sidecars
    return payload


def _log_tail(container_name):
    if not container_name:
        return []
    from core.logs import _read_docker_logs

    result = _read_docker_logs(container_name, tail=80)
    return sanitize_log_lines(result.get("lines") or [])


def _finding(issue_id, severity, confidence, title, plain, evidence, actions):
    return {
        "id": issue_id.lower(),
        "issue_id": issue_id,
        "severity": severity,
        "confidence": confidence,
        "title": title,
        "plain_language": plain,
        "evidence": evidence,
        "actions": actions,
    }


def _classify(service, snap: AddressSnapshot, probes) -> list[dict]:
    findings = []
    http = probes.get("http") or {}
    tcp = probes.get("tcp") or {}
    tcp_live = probes.get("tcp_live") or {}
    dns = probes.get("dns") or {}
    tls = probes.get("tls") or {}
    docker_info = probes.get("docker") or {}
    stats = probes.get("stats") or {}

    for row in diff_addresses(service, snap):
        actions = ["ACTION_RECHECK"]
        if row["issue_id"] == "ISSUE_PORT_CARD_DRIFT":
            actions = ["ACTION_SYNC_CARD_PORT", "ACTION_DISCOVER_PORT", "ACTION_UPDATE_LINKED_URLS", "ACTION_RECHECK"]
        elif row["issue_id"] == "ISSUE_PORT_INSTALLED_DRIFT":
            actions = ["ACTION_DISCOVER_PORT", "ACTION_SYNC_CARD_PORT"]
        elif row["issue_id"] == "ISSUE_HOST_STALE":
            actions = ["ACTION_REFRESH_HOST", "ACTION_SYNC_CARD_PORT"]
        elif row["issue_id"] == "ISSUE_HREF_DESYNC":
            actions = ["ACTION_UPDATE_LINKED_URLS", "ACTION_SYNC_CARD_PORT"]
        elif row["issue_id"] == "ISSUE_DOCKER_UNAVAILABLE":
            actions = ["ACTION_RECHECK", "ACTION_OPEN_SETTINGS"]
        elif row["issue_id"] == "ISSUE_MULTIPLE_BINDINGS":
            actions = ["ACTION_OPEN_EDITOR", "ACTION_OPEN_LOGS"]
        elif row["issue_id"] == "ISSUE_CONTAINER_MISSING":
            actions = ["ACTION_RETRY_INSTALL", "ACTION_OPEN_LIBRARY", "ACTION_RECHECK"]
            if docker_info.get("managed") and docker_info.get("install_status") == "error":
                actions = ["ACTION_RETRY_INSTALL", "ACTION_OPEN_LIBRARY"]
        findings.append(
            _finding(
                row["issue_id"],
                row["severity"],
                row["confidence"],
                FINDING_TITLES.get(row["issue_id"])
                or row.get("title")
                or row["issue_id"].replace("ISSUE_", "").replace("_", " ").title(),
                row["plain_language"],
                [{"probe_id": "PROBE_COMPARE_ADDRESSES", "summary": row["plain_language"], "data": redact_mapping({"card_port": service.port, "live_port": snap.port, "bindings": snap.bindings})}],
                actions,
            )
        )

    status = (docker_info.get("status") or "").lower()
    if docker_info.get("available") and docker_info.get("container"):
        if status == "paused":
            findings.append(
                _finding(
                    "ISSUE_CONTAINER_PAUSED",
                    "high",
                    0.95,
                    "Container is paused",
                    f"{service.name} is paused in Docker, so it cannot answer requests.",
                    [{"probe_id": "PROBE_DOCKER", "summary": "paused", "data": {"container": docker_info.get("container")}}],
                    ["ACTION_UNPAUSE", "ACTION_RECHECK"],
                )
            )
        elif status in ("exited", "dead", "created"):
            findings.append(
                _finding(
                    "ISSUE_CONTAINER_EXITED",
                    "high",
                    0.95,
                    "Container is stopped",
                    f"{service.name} is not running.",
                    [{"probe_id": "PROBE_DOCKER", "summary": status, "data": {"exit_code": docker_info.get("exit_code"), "oom": docker_info.get("oom_killed")}}],
                    ["ACTION_START", "ACTION_RESTART", "ACTION_OPEN_LOGS", "ACTION_RECHECK"],
                )
            )
        elif status == "restarting":
            findings.append(
                _finding(
                    "ISSUE_CONTAINER_RESTARTING",
                    "high",
                    0.9,
                    "Container is restarting",
                    f"{service.name} is stuck restarting. Another restart is unlikely to help until the crash reason is fixed.",
                    [{"probe_id": "PROBE_DOCKER", "summary": "restarting", "data": {"restart_count": docker_info.get("restart_count")}}],
                    ["ACTION_OPEN_LOGS", "ACTION_RECHECK"],
                )
            )
        if (docker_info.get("health") or "").lower() == "unhealthy":
            findings.append(
                _finding(
                    "ISSUE_DOCKER_UNHEALTHY",
                    "high",
                    0.88,
                    "Docker healthcheck failed",
                    f"Docker reports {service.name} as unhealthy even if the process is running.",
                    [{"probe_id": "PROBE_DOCKER", "summary": "unhealthy"}],
                    ["ACTION_RESTART", "ACTION_OPEN_LOGS", "ACTION_RECHECK"],
                )
            )
        if docker_info.get("oom_killed"):
            findings.append(
                _finding(
                    "ISSUE_OOM",
                    "high",
                    0.9,
                    "Container ran out of memory",
                    f"{service.name} was killed because the host or container ran out of memory.",
                    [{"probe_id": "PROBE_DOCKER", "summary": "OOMKilled"}],
                    ["ACTION_RESTART", "ACTION_OPEN_LOGS"],
                )
            )
        if docker_info.get("managed") and docker_info.get("restart_policy") in ("", "no"):
            findings.append(
                _finding(
                    "ISSUE_RESTART_POLICY_NO",
                    "medium",
                    0.8,
                    "Restart policy is off",
                    "This managed container will not come back after a crash.",
                    [{"probe_id": "PROBE_DOCKER", "summary": docker_info.get("restart_policy") or "no"}],
                    ["ACTION_RESTORE_RESTART_POLICY"],
                )
            )
        down_sidecars = [row for row in docker_info.get("sidecars") or [] if (row.get("status") or "") not in ("running",)]
        if down_sidecars:
            findings.append(
                _finding(
                    "ISSUE_SIDECAR_EXITED",
                    "high",
                    0.9,
                    "A supporting container is down",
                    "A database, cache, or worker for this app is not running.",
                    [{"probe_id": "PROBE_DEPENDENCIES", "summary": ", ".join(row["name"] for row in down_sidecars), "data": down_sidecars}],
                    ["ACTION_RESTART_STACK", "ACTION_OPEN_LOGS", "ACTION_RECHECK"],
                )
            )

    if docker_info.get("install_status") == "error":
        findings.append(
            _finding(
                "ISSUE_INSTALL_ERROR",
                "high",
                0.9,
                "Last install failed",
                redact_text(docker_info.get("install_error") or "The library install did not finish."),
                [{"probe_id": "PROBE_CONFIG_VALIDATE", "summary": "InstalledService.status=error"}],
                ["ACTION_RETRY_INSTALL", "ACTION_OPEN_LIBRARY", "ACTION_OPEN_LOGS"],
            )
        )

    if dns.get("ok") is False and not dns.get("skipped"):
        findings.append(
            _finding(
                "ISSUE_DNS",
                "high",
                0.85,
                "Hostname does not resolve",
                f"The hostname {service.host or 'on this card'} could not be resolved.",
                [{"probe_id": "PROBE_DNS", "summary": dns.get("error") or "dns failed"}],
                ["ACTION_REFRESH_HOST", "ACTION_OPEN_EDITOR", "ACTION_RECHECK"],
            )
        )
    if tcp.get("ok") is False and not tcp.get("skipped"):
        issue = "ISSUE_HTTP_CONN_REFUSED" if tcp.get("error") == "connection refused" else "ISSUE_TCP_TIMEOUT"
        if tcp.get("error") == "timeout":
            issue = "ISSUE_TCP_TIMEOUT"
        has_container = bool(docker_info.get("container") or snap.container_name)
        if has_container and snap.port and service.port and snap.port != service.port:
            tcp_actions = ["ACTION_SYNC_CARD_PORT", "ACTION_START", "ACTION_RESTART", "ACTION_RECHECK"]
        elif has_container:
            tcp_actions = ["ACTION_START", "ACTION_RESTART", "ACTION_OPEN_LOGS", "ACTION_RECHECK"]
        else:
            tcp_actions = ["ACTION_OPEN_EDITOR", "ACTION_RECHECK"]
        findings.append(
            _finding(
                issue,
                "high",
                0.86,
                "Nothing is listening on the card port" if issue == "ISSUE_HTTP_CONN_REFUSED" else "The card port did not answer",
                "Control Center could not open a TCP connection to the address on this card.",
                [{"probe_id": "PROBE_TCP_CARD", "summary": tcp.get("error") or "tcp failed", "data": {"host": service.host, "port": service.port}}],
                tcp_actions,
            )
        )
    if tcp_live.get("ok") and tcp.get("ok") is False and snap.port and service.port and snap.port != service.port:
        if not any(item["issue_id"] == "ISSUE_PORT_CARD_DRIFT" for item in findings):
            findings.append(
                _finding(
                    "ISSUE_PORT_CARD_DRIFT",
                    "high",
                    0.93,
                    "The card still opens the old port",
                    f"{service.name} is listening on port {snap.port}, but this card still points at {service.port}.",
                    [{"probe_id": "PROBE_TCP_LIVE", "summary": f"live {snap.port} ok; card {service.port} failed"}],
                    ["ACTION_SYNC_CARD_PORT", "ACTION_UPDATE_LINKED_URLS", "ACTION_RECHECK"],
                )
            )

    scheme = urlparse(_probe_url(service)).scheme
    if scheme == "https" and tls.get("ok") is False:
        reason = tls.get("reason") or ""
        issue = "ISSUE_TLS_HOSTNAME" if reason == "hostname" else "ISSUE_TLS_UNTRUSTED"
        findings.append(
            _finding(
                issue,
                "high",
                0.84,
                "HTTPS certificate problem",
                "The certificate for this service is not trusted or does not match the hostname.",
                [{"probe_id": "PROBE_TLS", "summary": tls.get("error") or "tls failed"}],
                ["ACTION_OPEN_EDITOR", "ACTION_RECHECK"],
            )
        )

    status_code = http.get("status")
    if http.get("ssrf_blocked"):
        findings.append(
            _finding(
                "ISSUE_HTTP_REDIRECT",
                "medium",
                0.7,
                "Redirect left this host",
                "The service redirected to a different host, so Troubleshoot stopped following it.",
                [{"probe_id": "PROBE_HTTP", "summary": http.get("error")}],
                ["ACTION_OPEN_EDITOR", "ACTION_RECHECK"],
            )
        )
    elif status_code in (401, 403):
        findings.append(
            _finding(
                "ISSUE_HTTP_AUTH",
                "medium",
                0.8,
                "The service asked for a login",
                "The app is reachable, but it is asking for a password or API key.",
                [{"probe_id": "PROBE_HTTP", "summary": f"HTTP {status_code}"}],
                ["ACTION_OPEN_CREDENTIALS", "ACTION_CLEAR_CACHES", "ACTION_RECHECK"],
            )
        )
    elif status_code == 404:
        findings.append(
            _finding(
                "ISSUE_HTTP_404",
                "medium",
                0.75,
                "The health URL was not found",
                "The host answered, but the path on this card does not exist.",
                [{"probe_id": "PROBE_HTTP", "summary": "HTTP 404"}],
                ["ACTION_OPEN_EDITOR", "ACTION_UPDATE_LINKED_URLS", "ACTION_RECHECK"],
            )
        )
    elif isinstance(status_code, int) and status_code >= 500:
        findings.append(
            _finding(
                "ISSUE_HTTP_5XX",
                "high",
                0.86,
                "The app returned a server error",
                f"{service.name} is running but returned HTTP {status_code}.",
                [{"probe_id": "PROBE_HTTP", "summary": f"HTTP {status_code}"}],
                ["ACTION_RESTART", "ACTION_OPEN_LOGS", "ACTION_RECHECK"],
            )
        )
    elif http.get("ok") is False and not http.get("skipped") and not tcp.get("ok") is False:
        findings.append(
            _finding(
                "ISSUE_HTTP_DOWN",
                "high",
                0.7,
                "HTTP check failed",
                redact_text(http.get("error") or "The HTTP probe failed."),
                [{"probe_id": "PROBE_HTTP", "summary": http.get("error") or "failed"}],
                ["ACTION_RECHECK", "ACTION_RESTART", "ACTION_OPEN_LOGS"],
            )
        )
    if http.get("x_frame_options") and "DENY" in str(http.get("x_frame_options")).upper():
        findings.append(
            _finding(
                "ISSUE_IFRAME_BLOCKED",
                "low",
                0.8,
                "This app blocks the overlay",
                "The service is up, but it refuses to be embedded. Use Open in a new tab.",
                [{"probe_id": "PROBE_HTTP", "summary": http.get("x_frame_options")}],
                ["ACTION_OPEN_OVERLAY"],
            )
        )

    mem = stats.get("memory_percent")
    disks = stats.get("disks") or []
    if isinstance(mem, (int, float)) and mem >= 92:
        findings.append(
            _finding(
                "ISSUE_HOST_MEMORY",
                "medium",
                0.7,
                "Host memory is nearly full",
                "The Pi is low on RAM, which can kill containers.",
                [{"probe_id": "PROBE_HOST", "summary": f"{mem}% memory"}],
                ["ACTION_RESTART", "ACTION_REBOOT_HOST"] if docker_info.get("oom_killed") else ["ACTION_RECHECK"],
            )
        )
    if any((disk.get("percent") or 0) >= 95 for disk in disks):
        findings.append(
            _finding(
                "ISSUE_HOST_DISK",
                "high",
                0.8,
                "Disk is nearly full",
                "A filesystem is almost full. New writes and container starts can fail.",
                [{"probe_id": "PROBE_HOST", "summary": "disk >= 95%"}],
                ["ACTION_OPEN_LOGS", "ACTION_RECHECK"],
            )
        )

    route = TunnelRoute.objects.filter(service_id=service.id).first()
    if route is None and service.catalog_slug:
        route = TunnelRoute.objects.filter(catalog_slug=service.catalog_slug).first()
    if route and service.port and str(service.port) not in (route.origin_url or ""):
        findings.append(
            _finding(
                "ISSUE_TUNNEL_ORIGIN_STALE",
                "medium",
                0.75,
                "Public tunnel origin is stale",
                "The Cloudflare route still points at an old LAN address.",
                [{"probe_id": "PROBE_COMPARE_ADDRESSES", "summary": redact_url(route.origin_url)}],
                ["ACTION_REPAIR_TUNNEL_ORIGIN", "ACTION_UPDATE_LINKED_URLS"],
            )
        )

    if service.kuma_monitor_id and service.href:
        findings  # kuma URL compare is best-effort via ISSUE_KUMA_URL_STALE after sync failures

    if not findings:
        if http.get("ok") or (docker_info.get("status") == "running" and tcp.get("ok")):
            findings.append(
                _finding(
                    "ISSUE_HEALTHY",
                    "info",
                    0.6,
                    "No problem found",
                    f"{service.name} looks reachable from here.",
                    [{"probe_id": "PROBE_HTTP", "summary": f"HTTP {http.get('status', 'ok')}"}],
                    ["ACTION_RECHECK"],
                )
            )
        else:
            findings.append(
                _finding(
                    "ISSUE_UNKNOWN",
                    "medium",
                    0.4,
                    "Could not pin down a single cause",
                    "The service is not healthy, but the automatic checks did not agree on one root cause.",
                    [{"probe_id": "PROBE_CONFIG_VALIDATE", "summary": "no high-confidence match"}],
                    ["ACTION_RECHECK", "ACTION_OPEN_LOGS", "ACTION_OPEN_EDITOR"],
                )
            )
    return findings


def _rank(findings):
    order = {"info": 0, "low": 1, "medium": 2, "high": 3}
    return sorted(
        findings,
        key=lambda row: (order.get(row.get("severity"), 0), row.get("confidence") or 0),
        reverse=True,
    )


def _has_container(service, snap=None):
    if isinstance(snap, dict) and snap.get("container_name"):
        return True
    slug = (service.catalog_slug or "").strip()
    if slug:
        return InstalledService.objects.filter(slug=slug).exclude(container_name="").exists()
    return False


def _decorate_actions(service, action_ids, is_superuser, snap=None):
    seen = []
    out = []
    has_container = _has_container(service, snap)
    for action_id in action_ids:
        if action_id in seen or action_id == "ACTION_UNINSTALL":
            continue
        if action_id == "ACTION_OPEN_LOGS" and not has_container:
            continue
        seen.append(action_id)
        meta = ACTION_META.get(action_id)
        if not meta:
            continue
        if meta.get("href"):
            item = {
                "action_id": action_id,
                "title": meta["title"],
                "risk": "safe",
                "confirm": False,
                "href": OPEN_HREFS[action_id](service),
            }
            out.append(item)
            continue
        if not is_superuser and action_id != "ACTION_RECHECK":
            continue
        item = {
            "action_id": action_id,
            "title": meta["title"],
            "risk": meta["risk"],
            "confirm": bool(meta.get("confirm")),
            "confirmation_language": meta.get("confirmation_language") or "",
        }
        out.append(item)
    return out


def _summary(service, findings):
    usable = [row for row in findings if row.get("issue_id") != "ISSUE_HEALTHY"]
    if not usable:
        return "Looks good from here."
    root = usable[0]
    return root.get("plain_language") or root.get("title") or "Needs attention."


def _overall_status(findings):
    usable = [row for row in findings if row.get("issue_id") != "ISSUE_HEALTHY"]
    if not usable:
        return DebugIncident.Status.HEALTHY
    auto = False
    for row in usable:
        for action_id in row.get("actions") or []:
            meta = ACTION_META.get(action_id) or {}
            if action_id.startswith("ACTION_OPEN"):
                continue
            if meta.get("risk") in ("safe", "disruptive", "destructive"):
                auto = True
    return DebugIncident.Status.NEEDS_ACTION if auto else DebugIncident.Status.MANUAL_ONLY


def _report_text(service, incident_id, findings, snap, probes):
    lines = [
        f"Control Center troubleshoot report {incident_id}",
        f"Generated: {timezone.now().isoformat()}",
        f"App version: {get_current_version()}",
        f"Service: {service.name} (id {service.id})",
        f"Catalog: {service.catalog_slug or '(custom)'}",
        f"Card URL: {redact_url(service.href or '')}",
        f"Health URL: {redact_url(service.health_check_url or '')}",
        f"Live source: {snap.source} {snap.host}:{snap.port or '-'}",
        f"Container: {snap.container_name or '-'} ({snap.container_status or '-'})",
        "",
        "Findings:",
    ]
    for row in findings:
        lines.append(f"- {row.get('issue_id')}: {row.get('plain_language')}")
    docker_info = probes.get("docker") or {}
    if docker_info.get("sidecars"):
        lines.append("")
        lines.append("Sidecars:")
        for item in docker_info["sidecars"]:
            lines.append(f"- {item.get('name')}: {item.get('status')}")
    logs = probes.get("logs") or []
    if logs:
        lines.append("")
        lines.append("Recent logs (redacted):")
        lines.extend(logs[:20])
    lines.append("")
    lines.append("Send this report as-is. Secrets have been removed.")
    return "\n".join(lines)


def diagnose_service(service, cancel_event=None, budget_s=BUDGET_S):
    started = time.monotonic()
    probes = {}
    url = _probe_url(service)
    parsed = urlparse(url)
    host = service.host or parsed.hostname or ""
    port = service.port or parsed.port
    snap = inspect_live_address(service)
    probes["address"] = {
        "source": snap.source,
        "host": snap.host,
        "port": snap.port,
        "bindings": snap.bindings,
        "conflict": snap.conflict,
        "confidence": snap.confidence,
        "container_name": snap.container_name,
        "container_status": snap.container_status,
    }

    def remaining():
        return budget_s - (time.monotonic() - started)

    if remaining() > 0.2:
        latest = (
            ServiceCheck.objects.filter(service=service).order_by("-checked_at").first()
        )
        probes["cached"] = {
            "is_up": None if latest is None else latest.is_up,
            "error": (latest.error if latest else "")[:200],
            "response_ms": latest.response_ms if latest else None,
        }

    workers = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        if remaining() > 1 and host and "." in host and not host.replace(".", "").isdigit():
            workers["dns"] = pool.submit(_dns_probe, host, min(1.0, remaining()))
        if remaining() > 1.2 and host and port:
            workers["tcp"] = pool.submit(_tcp_probe, host, port, min(1.5, remaining()))
        if remaining() > 1.2 and snap.host and snap.port and (snap.port != port or snap.host != host):
            workers["tcp_live"] = pool.submit(_tcp_probe, snap.host, snap.port, min(1.5, remaining()))
        if remaining() > 1:
            workers["docker"] = pool.submit(_docker_inspect, service)
        for name, future in list(workers.items()):
            try:
                probes[name] = future.result(timeout=max(0.2, remaining()))
            except Exception as exc:
                probes[name] = {"ok": False, "error": str(exc)[:200]}

    if cancel_event is not None and cancel_event.is_set():
        return snap, probes, []

    if parsed.scheme == "https" and host and port and remaining() > 1:
        probes["tls"] = _tls_probe(host, port, min(2.0, remaining()))
    tcp_ok = (probes.get("tcp") or {}).get("ok")
    if remaining() > 1 and url and tcp_ok is not False:
        probes["http"] = _http_probe(url, host, min(8.0, remaining()))
    if remaining() > 0.4:
        from dashboard.services import get_system_stats

        probes["stats"] = get_system_stats()
    container_name = snap.container_name or (probes.get("docker") or {}).get("container")
    if remaining() > 0.8 and container_name:
        probes["logs"] = _log_tail(container_name)

    findings = _rank(_classify(service, snap, probes))
    return snap, probes, findings


def incident_payload(incident, *, is_superuser=False, request=None):
    service = incident.service
    findings = incident.findings_json or []
    action_ids = []
    for row in findings:
        action_ids.extend(row.get("actions") or [])
    if "ACTION_RECHECK" not in action_ids:
        action_ids.append("ACTION_RECHECK")
    snap = (incident.snapshot_json or {}).get("address") or {}
    actions = _decorate_actions(service, action_ids, is_superuser, snap)
    if incident.status in (DebugIncident.Status.QUEUED, DebugIncident.Status.RUNNING):
        summary = f"Looking at {service.name}…"
    else:
        summary = _summary(service, findings)
    return {
        "incident_id": incident.incident_id,
        "status": incident.status,
        "service": {
            "id": service.id,
            "name": service.name,
            "catalog_slug": service.catalog_slug,
            "href": redact_url(service.href or ""),
            "port": service.port,
            "host": service.host,
        },
        "summary": summary,
        "can_repair": bool(is_superuser),
        "findings": findings,
        "actions": actions,
        "snapshot": redact_mapping(snap),
        "cache_bust": False,
        "finished_at": incident.finished_at.isoformat() if incident.finished_at else "",
        "poll_url": reverse("api_service_troubleshoot_poll", args=[service.id, incident.incident_id]),
        "report_url": reverse("api_service_troubleshoot_report_txt", args=[service.id, incident.incident_id]),
        "report_json_url": reverse("api_service_troubleshoot_report_json", args=[service.id, incident.incident_id]),
    }


def _release_diag_locks(service_id):
    cache.delete(f"debug:diag:{service_id}")
    current = cache.get("debug:diag:global") or 0
    try:
        current = int(current)
    except (TypeError, ValueError):
        current = 0
    cache.set("debug:diag:global", max(0, current - 1), DIAG_LOCK_TTL)


def _run_diagnosis(incident_pk):
    close_old_connections()
    service_id = None
    try:
        incident = DebugIncident.objects.select_related("service").get(pk=incident_pk)
        service_id = incident.service_id
        if incident.cancel_requested:
            incident.status = DebugIncident.Status.CANCELLED
            incident.finished_at = timezone.now()
            incident.save(update_fields=["status", "finished_at"])
            return
        incident.status = DebugIncident.Status.RUNNING
        incident.save(update_fields=["status"])
        cancel = threading.Event()
        if incident.cancel_requested:
            cancel.set()
        snap, probes, findings = diagnose_service(incident.service, cancel)
        incident.refresh_from_db()
        if incident.cancel_requested:
            incident.status = DebugIncident.Status.CANCELLED
            incident.finished_at = timezone.now()
            incident.save(update_fields=["status", "finished_at"])
            return
        incident.findings_json = findings
        incident.snapshot_json = {
            "address": probes.get("address") or {},
            "docker": probes.get("docker") or {},
            "http": probes.get("http") or {},
            "tcp": probes.get("tcp") or {},
        }
        incident.actions_json = []
        for row in findings:
            incident.actions_json.extend(row.get("actions") or [])
        incident.report_text = _report_text(incident.service, incident.incident_id, findings, snap, probes)
        incident.status = _overall_status(findings)
        incident.finished_at = timezone.now()
        incident.save()
        log_audit(
            "admin",
            user=incident.actor,
            message=f"Debug diagnosis {incident.incident_id} for {incident.service.name}",
            incident_id=incident.incident_id,
            service=incident.service.name,
            status=incident.status,
        )
    except Exception:
        logger.exception("Debug diagnosis failed")
        try:
            DebugIncident.objects.filter(pk=incident_pk).update(
                status=DebugIncident.Status.FAILED,
                finished_at=timezone.now(),
            )
        except Exception:
            pass
    finally:
        if service_id is not None:
            _release_diag_locks(service_id)
        close_old_connections()


def start_diagnosis(service, actor):
    user_key = f"debug:rl:{getattr(actor, 'pk', 0) or 0}"
    count = cache.get(user_key) or 0
    if count >= RATE_LIMIT:
        return None, "Too many troubleshoot runs. Wait a few minutes."
    cache.set(user_key, count + 1, RATE_WINDOW)
    global_key = "debug:diag:global"
    if not cache.add(f"debug:diag:{service.id}", "1", DIAG_LOCK_TTL):
        running = (
            DebugIncident.objects.filter(
                service=service,
                status__in=[DebugIncident.Status.QUEUED, DebugIncident.Status.RUNNING],
            )
            .order_by("-created_at")
            .first()
        )
        if running:
            return running, ""
    current = cache.get(global_key) or 0
    if current >= GLOBAL_CONCURRENCY:
        return None, "Troubleshoot is busy. Try again in a moment."
    cache.set(global_key, current + 1, DIAG_LOCK_TTL)
    incident = DebugIncident.objects.create(
        incident_id=new_incident_id(),
        service=service,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        status=DebugIncident.Status.QUEUED,
    )
    thread = threading.Thread(
        target=_run_diagnosis,
        args=(incident.pk,),
        name=f"debug-{incident.incident_id}",
        daemon=True,
    )
    thread.start()
    incident.refresh_from_db()
    return incident, ""


def prune_incidents(days=14):
    cutoff = timezone.now() - timezone.timedelta(days=days)
    deleted, _ = DebugIncident.objects.filter(created_at__lt=cutoff).delete()
    return deleted
