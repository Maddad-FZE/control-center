"""Uptime Kuma client: opt-in install, generated admin, monitor sync, status pull."""

import logging
import secrets

from core.models import SiteSettings
from core.site_settings import clear_site_settings_cache
from dashboard.models import Service
from library.installer import get_docker_client, services_host
from library.models import InstalledService

logger = logging.getLogger(__name__)

KUMA_SLUG = "uptime-kuma"
KUMA_USERNAME = "cc-monitor"
MONITOR_INTERVAL = 60

_client_factory = None


def set_client_factory(factory):
    """Tests inject a fake Socket.IO client. Pass None to restore the default."""
    global _client_factory
    _client_factory = factory


def kuma_is_running():
    return InstalledService.objects.filter(
        slug=KUMA_SLUG,
        status=InstalledService.Status.RUNNING,
        host_port__gt=0,
    ).exists()


def kuma_is_present():
    """True once Library has a Kuma row — including while it is installing."""
    return InstalledService.objects.filter(
        slug=KUMA_SLUG,
        status__in=(
            InstalledService.Status.INSTALLING,
            InstalledService.Status.RUNNING,
            InstalledService.Status.STOPPED,
        ),
    ).exists()


def kuma_base_url():
    row = InstalledService.objects.filter(
        slug=KUMA_SLUG,
        status=InstalledService.Status.RUNNING,
        host_port__gt=0,
    ).first()
    if not row:
        return ""
    host = services_host() or "127.0.0.1"
    return f"http://{host}:{row.host_port}"


def kuma_api_urls():
    """URLs tick can use. Prefer the container IP so Docker-to-Docker works."""
    urls = []
    row = InstalledService.objects.filter(
        slug=KUMA_SLUG,
        status=InstalledService.Status.RUNNING,
        host_port__gt=0,
    ).first()
    if row:
        try:
            container = get_docker_client().containers.get(
                row.container_name or f"cc-{KUMA_SLUG}"
            )
            nets = container.attrs.get("NetworkSettings") or {}
            ip = (nets.get("IPAddress") or "").strip()
            if not ip:
                for net in (nets.get("Networks") or {}).values():
                    ip = (net.get("IPAddress") or "").strip()
                    if ip:
                        break
            if ip:
                urls.append(f"http://{ip}:3001")
        except Exception as exc:
            logger.debug("Kuma container IP unavailable: %s", exc)
    lan = kuma_base_url()
    if lan and lan not in urls:
        urls.append(lan)
    return urls


def _start_stopped_container(row):
    name = row.container_name or f"cc-{KUMA_SLUG}"
    try:
        container = get_docker_client().containers.get(name)
        container.start()
        InstalledService.objects.filter(pk=row.pk).update(
            status=InstalledService.Status.RUNNING,
            error="",
        )
        return InstalledService.objects.filter(pk=row.pk).first()
    except Exception as exc:
        logger.debug("Could not start stopped Kuma container: %s", exc)
        return None


def ensure_kuma_installed():
    """Use an existing Kuma install. Never auto-install or add a dashboard card."""
    try:
        row = InstalledService.objects.filter(slug=KUMA_SLUG).first()
        if row and row.status == InstalledService.Status.RUNNING and row.host_port:
            return row
        if row and row.status == InstalledService.Status.STOPPED:
            return _start_stopped_container(row)
        return None
    except Exception:
        logger.exception("Uptime Kuma ensure failed")
        return None


def delete_monitor_for_service(service):
    """Remove the Kuma HTTP monitor for a dashboard card. Never raises."""
    if service is None:
        return
    mid = getattr(service, "kuma_monitor_id", None)
    href = (getattr(service, "href", None) or "").strip()
    if getattr(service, "catalog_slug", "") == KUMA_SLUG:
        return
    if not mid and not href:
        return
    api = connect_kuma()
    if api is None:
        return
    try:
        if mid:
            api.delete_monitor(int(mid))
            return
        for monitor in api.get_monitors() or []:
            url = (monitor.get("url") or "").rstrip("/")
            if url == href.rstrip("/"):
                found = _monitor_id(monitor)
                if found:
                    api.delete_monitor(found)
                break
    except Exception as exc:
        logger.debug("Could not delete Kuma monitor for %s: %s", getattr(service, "name", "?"), exc)
    finally:
        if hasattr(api, "disconnect"):
            try:
                api.disconnect()
            except Exception:
                pass


def delete_monitors_for_services(services):
    for service in services:
        delete_monitor_for_service(service)


def _ensure_creds(create=False):
    site = SiteSettings.load()
    if not create:
        return site
    changed = []
    if not site.kuma_username:
        site.kuma_username = KUMA_USERNAME
        changed.append("kuma_username")
    if not site.kuma_password:
        site.kuma_password = secrets.token_urlsafe(18)
        changed.append("kuma_password")
    if changed:
        site.save(update_fields=changed)
        clear_site_settings_cache()
        site = SiteSettings.load()
    return site


def _default_factory(url):
    from uptime_kuma_api import UptimeKumaApi

    return UptimeKumaApi(url, timeout=8)


def _monitor_type_http():
    try:
        from uptime_kuma_api import MonitorType

        return MonitorType.HTTP
    except ImportError:
        return "http"


def _login_kuma(api):
    needs_setup = bool(getattr(api, "need_setup", lambda: False)())
    if needs_setup:
        site = _ensure_creds(create=True)
        api.setup(site.kuma_username, site.kuma_password)
    else:
        site = _ensure_creds(create=False)
        if not site.kuma_username or not site.kuma_password:
            raise RuntimeError(
                "Uptime Kuma already has an admin. Save that username and password under Settings → Site."
            )
    api.login(site.kuma_username, site.kuma_password)
    if not site.kuma_setup_done:
        site.kuma_setup_done = True
        site.save(update_fields=["kuma_setup_done"])
        clear_site_settings_cache()
    return api


def connect_kuma(url=None):
    urls = [url] if url else kuma_api_urls()
    if not urls:
        return None
    factory = _client_factory or _default_factory
    last_error = None
    for candidate in urls:
        api = None
        try:
            api = factory(candidate)
            return _login_kuma(api)
        except Exception as exc:
            last_error = exc
            logger.warning("Uptime Kuma connect failed at %s: %s", candidate, exc)
            if api is not None and hasattr(api, "disconnect"):
                try:
                    api.disconnect()
                except Exception:
                    pass
    if last_error:
        logger.warning("Uptime Kuma is running but Control Center could not log in: %s", last_error)
    return None


def _monitor_id(payload):
    if payload is None:
        return None
    raw = payload.get("monitorID", payload.get("monitorId", payload.get("id")))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _monitored_services():
    return list(
        Service.objects.filter(enabled=True)
        .exclude(catalog_slug=KUMA_SLUG)
        .exclude(name__iexact="Uptime Kuma")
        .exclude(href="")
    )


def sync_monitors(api):
    """Add or update an HTTP monitor per enabled card href. Skip the Kuma card."""
    try:
        existing = list(api.get_monitors() or [])
    except Exception as exc:
        logger.debug("Kuma get_monitors failed: %s", exc)
        existing = []
    by_id = {}
    by_url = {}
    for monitor in existing:
        mid = _monitor_id(monitor)
        if mid is not None:
            by_id[mid] = monitor
        url = (monitor.get("url") or "").rstrip("/")
        if url:
            by_url[url] = monitor

    http_type = _monitor_type_http()
    for service in _monitored_services():
        href = (service.href or "").strip()
        if not href:
            continue
        key = href.rstrip("/")
        monitor = None
        if service.kuma_monitor_id:
            monitor = by_id.get(service.kuma_monitor_id)
        if monitor is None:
            monitor = by_url.get(key)
        try:
            if monitor is None:
                result = api.add_monitor(
                    type=http_type,
                    name=service.name,
                    url=href,
                    interval=MONITOR_INTERVAL,
                )
                mid = _monitor_id(result)
            else:
                mid = _monitor_id(monitor)
                current_url = monitor.get("url") or ""
                current_name = monitor.get("name") or ""
                if current_url != href or current_name != service.name:
                    api.edit_monitor(
                        mid,
                        name=service.name,
                        url=href,
                        interval=MONITOR_INTERVAL,
                    )
            if mid and service.kuma_monitor_id != mid:
                service.kuma_monitor_id = mid
                service.save(update_fields=["kuma_monitor_id"])
        except Exception:
            logger.exception("Could not sync Kuma monitor for %s", service.name)


def _heartbeat_verdict(status):
    name = getattr(status, "name", None)
    if name == "UP":
        return True
    if name == "DOWN":
        return False
    if status in (1, "1", "UP"):
        return True
    if status in (0, "0", "DOWN"):
        return False
    return None


def _heartbeats_for(heartbeats, monitor_id):
    if not heartbeats or monitor_id is None:
        return []
    return heartbeats.get(monitor_id) or heartbeats.get(str(monitor_id)) or []


def read_status(api):
    """Return [(service, is_up, response_ms, error), ...] from recent heartbeats."""
    try:
        heartbeats = api.get_heartbeats() or {}
    except Exception as exc:
        logger.debug("Kuma get_heartbeats failed: %s", exc)
        return []

    out = []
    for service in _monitored_services():
        beats = _heartbeats_for(heartbeats, service.kuma_monitor_id)
        if not beats:
            continue
        last = beats[-1]
        verdict = _heartbeat_verdict(last.get("status") if isinstance(last, dict) else None)
        if verdict is None:
            continue
        ping = last.get("ping") if isinstance(last, dict) else None
        try:
            ms = int(round(float(ping))) if ping is not None else None
            if ms is not None and ms < 0:
                ms = None
        except (TypeError, ValueError):
            ms = None
        err = ""
        if not verdict:
            err = str((last.get("msg") if isinstance(last, dict) else "") or "Monitor down")[:200]
        out.append((service, verdict, ms, err))
    return out


def pull_status():
    """Ensure Kuma, sync monitors, return status rows. None if Kuma is unavailable."""
    row = ensure_kuma_installed()
    if row is None:
        return None
    api = connect_kuma()
    if api is None:
        return None
    try:
        sync_monitors(api)
        return read_status(api)
    finally:
        if hasattr(api, "disconnect"):
            try:
                api.disconnect()
            except Exception:
                pass
