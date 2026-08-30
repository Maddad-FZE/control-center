"""Cloudflare Tunnel API, connector start, and publish guards."""

import json
import logging
from urllib.parse import quote, urlparse

import requests

from core.models import SiteSettings
from core.site_settings import clear_site_settings_cache
from library.catalog import get_docker_spec, get_service_by_slug
from library.installer import (
    DOCKER_LABEL_SLUG,
    TUNNEL_SLUG,
    _image_version,
    _remove_container,
    get_docker_client,
    services_host,
)
from library.models import InstalledService, TunnelRoute

logger = logging.getLogger(__name__)

API_BASE = "https://api.cloudflare.com/client/v4"
TUNNEL_NAME = "control-center"
CC_PORTS = {8099}
TOKEN_PERMISSIONS = [
    {"key": "argotunnel", "type": "edit"},
    {"key": "account_settings", "type": "read"},
    {"key": "dns", "type": "edit"},
    {"key": "zone", "type": "read"},
]
AUTH_HINT = (
    "Cloudflare rejected this token for tunnels. "
    "Create a new token from the button and confirm Account includes Cloudflare Tunnel Edit."
)

_http = None


def set_http_session(session):
    """Tests inject a fake requests session. Pass None to restore."""
    global _http
    _http = session


def token_create_url():
    perms = quote(json.dumps(TOKEN_PERMISSIONS, separators=(",", ":")))
    return (
        "https://dash.cloudflare.com/profile/api-tokens"
        f"?permissionGroupKeys={perms}&accountId=*&zoneId=all"
        "&name=Control+Center+Tunnel"
    )


def tunnel_is_installed():
    return InstalledService.objects.filter(slug=TUNNEL_SLUG).exclude(
        status=InstalledService.Status.ERROR,
    ).exists()


def tunnel_is_linked():
    site = SiteSettings.load()
    return bool(site.cf_api_token and site.cf_tunnel_id and site.cf_tunnel_token)


def _clean_token(raw):
    token = (raw or "").strip().strip('"').strip("'")
    if " " in token:
        for part in reversed(token.split()):
            if len(part) >= 20:
                return part
    return token


def _headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _api_error_message(payload, status_code):
    errors = payload.get("errors") or []
    first = errors[0] if errors else {}
    msg = first.get("message") or f"Cloudflare HTTP {status_code}"
    code = first.get("code")
    if code == 10000 or msg.strip().lower() == "authentication error":
        return AUTH_HINT
    return msg


def _request(method, path, token, **kwargs):
    session = _http if _http is not None else requests
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    resp = session.request(method, url, headers=_headers(token), timeout=20, **kwargs)
    try:
        payload = resp.json()
    except ValueError:
        payload = {"success": False, "errors": [{"message": resp.text[:200]}]}
    if resp.status_code >= 400 or not payload.get("success", True):
        raise RuntimeError(_api_error_message(payload, resp.status_code))
    return payload.get("result")


def list_accounts(token):
    try:
        result = _request("GET", "/accounts", token) or []
    except RuntimeError:
        result = []
    if isinstance(result, dict):
        result = result.get("accounts") or []
    return [{"id": row.get("id", ""), "name": row.get("name", "")} for row in result if row.get("id")]


def list_zones(token, account_id=""):
    path = "/zones"
    if account_id:
        path = f"/zones?account.id={account_id}"
    try:
        result = _request("GET", path, token) or []
    except RuntimeError:
        result = []
    zones = []
    for row in result:
        account = row.get("account") or {}
        zones.append(
            {
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "account_id": account.get("id", ""),
                "account_name": account.get("name", ""),
            }
        )
    return [row for row in zones if row["id"]]


def _accounts_from_zones(zones):
    seen = {}
    for row in zones:
        account_id = row.get("account_id") or ""
        if not account_id or account_id in seen:
            continue
        seen[account_id] = {
            "id": account_id,
            "name": row.get("account_name") or account_id,
        }
    return list(seen.values())


def discover_accounts_and_zones(token):
    """Tunnel+DNS tokens often cannot GET /accounts; zones still work."""
    zones = list_zones(token)
    accounts = list_accounts(token) or _accounts_from_zones(zones)
    return accounts, zones


def _tunnel_token_from_result(result):
    if isinstance(result, str):
        return result
    if not result:
        return ""
    token = result.get("token") or ""
    if not token:
        token = (result.get("credentials_file") or {}).get("token") or ""
    return token


def _create_or_reuse_tunnel(token, account_id, name):
    existing = _request("GET", f"/accounts/{account_id}/cfd_tunnel", token) or []
    if isinstance(existing, dict):
        existing = [existing]
    for row in existing:
        if row.get("name") == name and not row.get("deleted_at"):
            tunnel_id = row.get("id")
            token_result = _request(
                "GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token", token
            )
            return tunnel_id, _tunnel_token_from_result(token_result)
    created = _request(
        "POST",
        f"/accounts/{account_id}/cfd_tunnel",
        token,
        json={"name": name, "config_src": "cloudflare"},
    )
    return created.get("id"), _tunnel_token_from_result(created)


def _preview_payload(accounts, zones):
    return {
        "preview": True,
        "needs_choice": True,
        "accounts": accounts,
        "zones": zones,
    }


def link_account(api_token, account_id="", zone_id="", confirm=False):
    api_token = _clean_token(api_token)
    if not api_token:
        raise RuntimeError("Paste a Cloudflare API token.")
    accounts, zones = discover_accounts_and_zones(api_token)
    if not accounts and not zones:
        raise RuntimeError(
            "That token cannot see a Cloudflare account or DNS zone. "
            "Create a new token from the button, leave Account and Zone on All, then paste it."
        )
    if not confirm:
        return _preview_payload(accounts, zones)
    if account_id:
        account = next((row for row in accounts if row["id"] == account_id), None)
        if not account:
            raise RuntimeError("Unknown Cloudflare account.")
    elif len(accounts) == 1:
        account = accounts[0]
    else:
        return {"needs_choice": True, "accounts": accounts, "zones": zones}

    if account["id"]:
        zones = [row for row in zones if not row.get("account_id") or row["account_id"] == account["id"]]
        if not zones:
            zones = list_zones(api_token, account["id"])
    if zone_id:
        zone = next((row for row in zones if row["id"] == zone_id), None)
        if not zone:
            raise RuntimeError("Unknown Cloudflare zone.")
    elif len(zones) == 1:
        zone = zones[0]
    elif not zones:
        raise RuntimeError("That account has no DNS zones.")
    else:
        return {"needs_choice": True, "accounts": accounts, "zones": zones}

    tunnel_id, tunnel_token = _create_or_reuse_tunnel(api_token, account["id"], TUNNEL_NAME)
    if not tunnel_id or not tunnel_token:
        raise RuntimeError("Cloudflare did not return a tunnel token.")

    site = SiteSettings.load()
    site.cf_api_token = api_token
    site.cf_account_id = account["id"]
    site.cf_zone_id = zone["id"]
    site.cf_zone_name = zone["name"]
    site.cf_tunnel_id = tunnel_id
    site.cf_tunnel_token = tunnel_token
    site.cf_tunnel_name = TUNNEL_NAME
    site.save(
        update_fields=[
            "cf_api_token",
            "cf_account_id",
            "cf_zone_id",
            "cf_zone_name",
            "cf_tunnel_id",
            "cf_tunnel_token",
            "cf_tunnel_name",
        ]
    )
    clear_site_settings_cache()
    try:
        start_connector()
    except Exception as exc:
        logger.warning("Tunnel linked but connector did not start: %s", exc)
    return {
        "ok": True,
        "account_id": account["id"],
        "zone_id": zone["id"],
        "zone_name": zone["name"],
        "tunnel_id": tunnel_id,
    }


def unlink_account(delete_remote=False):
    site = SiteSettings.load()
    if delete_remote and site.cf_api_token and site.cf_account_id and site.cf_tunnel_id:
        try:
            _request(
                "DELETE",
                f"/accounts/{site.cf_account_id}/cfd_tunnel/{site.cf_tunnel_id}",
                site.cf_api_token,
            )
        except Exception as exc:
            logger.warning("Could not delete remote tunnel: %s", exc)
    stop_connector()
    TunnelRoute.objects.all().delete()
    site.cf_api_token = ""
    site.cf_account_id = ""
    site.cf_zone_id = ""
    site.cf_zone_name = ""
    site.cf_tunnel_id = ""
    site.cf_tunnel_token = ""
    site.cf_tunnel_name = ""
    site.save(
        update_fields=[
            "cf_api_token",
            "cf_account_id",
            "cf_zone_id",
            "cf_zone_name",
            "cf_tunnel_id",
            "cf_tunnel_token",
            "cf_tunnel_name",
        ]
    )
    clear_site_settings_cache()


def start_connector():
    site = SiteSettings.load()
    if not site.cf_tunnel_token:
        return None
    entry = get_service_by_slug(TUNNEL_SLUG)
    if not entry:
        return None
    spec = get_docker_spec(entry)
    image = spec.get("image") or "cloudflare/cloudflared:latest"
    client = get_docker_client()
    name = f"cc-{TUNNEL_SLUG}"
    _remove_container(client, name)
    client.containers.run(
        image,
        name=name,
        detach=True,
        command=["tunnel", "--no-autoupdate", "run"],
        environment={"TUNNEL_TOKEN": site.cf_tunnel_token},
        labels={DOCKER_LABEL_SLUG: TUNNEL_SLUG},
        restart_policy={"Name": "unless-stopped"},
    )
    InstalledService.objects.filter(slug=TUNNEL_SLUG).update(
        container_name=name,
        host_port=0,
        installed_version=_image_version(client, image),
        status=InstalledService.Status.RUNNING,
        error="",
    )
    return InstalledService.objects.filter(slug=TUNNEL_SLUG).first()


def stop_connector():
    name = f"cc-{TUNNEL_SLUG}"
    try:
        client = get_docker_client()
        _remove_container(client, name)
    except Exception as exc:
        logger.debug("Could not stop tunnel connector: %s", exc)
    InstalledService.objects.filter(slug=TUNNEL_SLUG).update(
        status=InstalledService.Status.STOPPED,
        error="",
    )


def is_control_center_target(origin_url="", catalog_slug="", port=None, request=None):
    slug = (catalog_slug or "").strip().lower()
    if slug in {TUNNEL_SLUG, "control-center"}:
        return True
    try:
        port_num = int(port) if port not in (None, "") else None
    except (TypeError, ValueError):
        port_num = None
    parsed = urlparse(origin_url or "")
    if port_num is None and parsed.port:
        port_num = parsed.port
    if port_num in CC_PORTS:
        return True
    if request:
        here = urlparse(request.build_absolute_uri("/"))
        here_port = here.port or (443 if here.scheme == "https" else 80)
        there_host = (parsed.hostname or "").lower()
        here_host = (here.hostname or "").lower()
        there_port = parsed.port or port_num or (443 if parsed.scheme == "https" else 80)
        if there_host and here_host and there_host == here_host and there_port == here_port:
            return True
    return False


def _zone_name():
    return (SiteSettings.load().cf_zone_name or "").strip().lower().rstrip(".")


def _is_tunnel_zone_host(host):
    zone = _zone_name()
    host = (host or "").strip().lower().rstrip(".")
    if not zone or not host:
        return False
    return host == zone or host.endswith(f".{zone}")


def ingress_origin(origin_url, catalog_slug=""):
    """Cloudflare ingress service must be scheme://host:port with no path."""
    parsed = urlparse((origin_url or "").strip())
    host = parsed.hostname or ""
    scheme = parsed.scheme if parsed.scheme in ("http", "https") else "http"
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    if not host:
        return ""
    if _is_tunnel_zone_host(host):
        host = services_host()
        scheme = "http"
        entry = get_service_by_slug((catalog_slug or "").strip())
        try:
            catalog_port = int((entry or {}).get("default_port") or 0)
        except (TypeError, ValueError):
            catalog_port = 0
        if catalog_port:
            port = catalog_port
        elif port in (80, 443):
            return ""
    return f"{scheme}://{host}:{int(port)}"


def origin_for_service(service=None, catalog_slug="", host_port=0):
    host = ""
    port = None
    scheme = "http"
    href_host = ""
    try:
        port_hint = int(host_port) if host_port else 0
    except (TypeError, ValueError):
        port_hint = 0
    if service is not None:
        host = (service.host or "").strip()
        port = service.port or None
        parsed = urlparse(service.href or "")
        href_host = parsed.hostname or ""
        if not host:
            host = href_host
        if not port:
            port = parsed.port
            if port is None and parsed.scheme in ("http", "https"):
                port = 443 if parsed.scheme == "https" else 80
        if parsed.scheme == "https" and not (service.host or "").strip():
            scheme = "https"
        catalog_slug = catalog_slug or service.catalog_slug
    catalog_port = 0
    entry = get_service_by_slug((catalog_slug or "").strip())
    if entry:
        try:
            catalog_port = int(entry.get("default_port") or 0)
        except (TypeError, ValueError):
            catalog_port = 0
    public_origin = _is_tunnel_zone_host(host) or _is_tunnel_zone_host(href_host)
    if public_origin or not host:
        host = services_host()
        scheme = "http"
        if public_origin or not port:
            port = port_hint or catalog_port or (None if public_origin else port)
    if not host or not port:
        return ""
    return ingress_origin(f"{scheme}://{host}:{int(port)}")


def _sync_ingress(site, routes):
    ingress = []
    for route in routes:
        service = ingress_origin(route.origin_url, catalog_slug=route.catalog_slug)
        if not service:
            continue
        if service != route.origin_url:
            route.origin_url = service
            route.save(update_fields=["origin_url"])
        ingress.append({"hostname": route.hostname, "service": service})
    ingress.append({"service": "http_status:404"})
    _request(
        "PUT",
        f"/accounts/{site.cf_account_id}/cfd_tunnel/{site.cf_tunnel_id}/configurations",
        site.cf_api_token,
        json={"config": {"ingress": ingress}},
    )


def _dns_name(hostname, zone_name):
    host = hostname.strip().rstrip(".").lower()
    zone = (zone_name or "").strip().rstrip(".").lower()
    if host == zone:
        return "@"
    suffix = f".{zone}"
    if host.endswith(suffix):
        return host[: -len(suffix)]
    return host


def _ensure_cname(site, hostname):
    name = _dns_name(hostname, site.cf_zone_name)
    content = f"{site.cf_tunnel_id}.cfargotunnel.com"
    existing = _request(
        "GET",
        f"/zones/{site.cf_zone_id}/dns_records?type=CNAME&name={hostname}",
        site.cf_api_token,
    ) or []
    body = {"type": "CNAME", "name": name, "content": content, "proxied": True}
    if existing:
        record_id = existing[0].get("id")
        _request("PUT", f"/zones/{site.cf_zone_id}/dns_records/{record_id}", site.cf_api_token, json=body)
        return
    _request("POST", f"/zones/{site.cf_zone_id}/dns_records", site.cf_api_token, json=body)


def _delete_cname(site, hostname):
    existing = _request(
        "GET",
        f"/zones/{site.cf_zone_id}/dns_records?type=CNAME&name={hostname}",
        site.cf_api_token,
    ) or []
    for row in existing:
        try:
            _request("DELETE", f"/zones/{site.cf_zone_id}/dns_records/{row.get('id')}", site.cf_api_token)
        except Exception as exc:
            logger.warning("Could not delete DNS for %s: %s", hostname, exc)


def compose_hostname(subdomain="", hostname="", zone_name=""):
    zone = (zone_name or "").strip().lower().rstrip(".")
    host = (hostname or "").strip().lower().rstrip(".")
    sub = (subdomain or "").strip().lower().rstrip(".")
    if host.endswith(f".{zone}") if zone else "." in host:
        return host
    label = sub or host
    if not label:
        raise RuntimeError("Enter a subdomain, for example photos.")
    if "." in label:
        if zone and label.endswith(f".{zone}"):
            return label
        raise RuntimeError("Enter only the subdomain. The zone is not editable.")
    if not zone:
        raise RuntimeError("Link a Cloudflare zone first.")
    return f"{label}.{zone}"


def publish_route(hostname, origin_url, catalog_slug="", service_id=None, request=None, subdomain=""):
    if not tunnel_is_linked():
        raise RuntimeError("Link a Cloudflare account in Settings first.")
    site = SiteSettings.load()
    hostname = compose_hostname(
        subdomain=subdomain,
        hostname=hostname,
        zone_name=site.cf_zone_name,
    )
    origin_url = ingress_origin(origin_url, catalog_slug=catalog_slug)
    if not origin_url:
        raise RuntimeError("That service has no address to publish.")
    if is_control_center_target(
        origin_url=origin_url,
        catalog_slug=catalog_slug,
        request=request,
    ):
        raise RuntimeError("Control Center stays on the LAN.")
    if site.cf_zone_name and not hostname.endswith(site.cf_zone_name.lower()):
        raise RuntimeError(f"Hostname must end with {site.cf_zone_name}.")
    route, created = TunnelRoute.objects.update_or_create(
        hostname=hostname,
        defaults={
            "catalog_slug": catalog_slug or "",
            "service_id": service_id,
            "origin_url": origin_url,
        },
    )
    routes = list(TunnelRoute.objects.order_by("hostname"))
    _sync_ingress(site, routes)
    _ensure_cname(site, hostname)
    return route


def unpublish_route(hostname):
    hostname = (hostname or "").strip().lower().rstrip(".")
    route = TunnelRoute.objects.filter(hostname=hostname).first()
    if not route:
        raise RuntimeError("That hostname is not published.")
    site = SiteSettings.load()
    route.delete()
    if tunnel_is_linked():
        _sync_ingress(site, list(TunnelRoute.objects.order_by("hostname")))
        _delete_cname(site, hostname)
    return True


def status_payload():
    site = SiteSettings.load()
    routes = [
        {
            "hostname": row.hostname,
            "origin_url": row.origin_url,
            "catalog_slug": row.catalog_slug,
            "service_id": row.service_id,
        }
        for row in TunnelRoute.objects.order_by("hostname")
    ]
    row = InstalledService.objects.filter(slug=TUNNEL_SLUG).first()
    return {
        "installed": tunnel_is_installed(),
        "linked": tunnel_is_linked(),
        "install_status": row.status if row else "none",
        "zone_name": site.cf_zone_name,
        "tunnel_id": site.cf_tunnel_id,
        "token_url": token_create_url(),
        "routes": routes,
    }
