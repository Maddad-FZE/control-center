import logging
import time
from urllib.parse import urljoin

import docker
import psutil
import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from core.models import log_audit
from core.site_settings import get_site_settings
from .models import Alert, Service, ServiceCheck

logger = logging.getLogger(__name__)

CHECK_THROTTLE_SECONDS = 25
PSEUDO_FSTYPES = {
    "squashfs",
    "overlay",
    "tmpfs",
    "devtmpfs",
    "proc",
    "sysfs",
    "devpts",
    "cgroup",
    "cgroup2",
    "mqueue",
    "hugetlbfs",
    "tracefs",
    "debugfs",
    "securityfs",
    "pstore",
    "bpf",
    "configfs",
    "fusectl",
    "binfmt_misc",
}


def get_system_stats():
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    disks_by_device = {}
    for part in psutil.disk_partitions(all=False):
        if part.fstype in PSEUDO_FSTYPES:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            entry = {
                "mount": part.mountpoint,
                "percent": usage.percent,
                "used_gb": round(usage.used / (1024**3), 1),
                "total_gb": round(usage.total / (1024**3), 1),
            }
            device = part.device
            if device not in disks_by_device or len(part.mountpoint) < len(
                disks_by_device[device]["mount"]
            ):
                disks_by_device[device] = entry
        except PermissionError:
            continue
    disks = list(disks_by_device.values())
    temp = None
    if hasattr(psutil, "sensors_temperatures"):
        temps = psutil.sensors_temperatures()
        if temps:
            for readings in temps.values():
                if readings:
                    temp = readings[0].current
                    break
    boot = psutil.boot_time()
    uptime_s = int(time.time() - boot)
    net = psutil.net_io_counters()
    return {
        "cpu_percent": cpu,
        "load_avg": list(getattr(psutil, "getloadavg", lambda: (0, 0, 0))()),
        "memory_percent": mem.percent,
        "memory_used_gb": round(mem.used / (1024**3), 1),
        "memory_total_gb": round(mem.total / (1024**3), 1),
        "disks": disks,
        "temperature_c": temp,
        "uptime_seconds": uptime_s,
        "network_sent_mb": round(net.bytes_sent / (1024**2), 1),
        "network_recv_mb": round(net.bytes_recv / (1024**2), 1),
    }


def get_docker_containers():
    try:
        client = docker.DockerClient(base_url=settings.DOCKER_HOST)
        containers = client.containers.list(all=True)
        out = []
        for c in containers:
            out.append(
                {
                    "name": c.name,
                    "image": (c.image.tags[0] if c.image.tags else c.image.short_id),
                    "status": c.status,
                    "state": c.attrs.get("State", {}).get("Status", c.status),
                }
            )
        return {"available": True, "containers": out}
    except Exception as exc:
        logger.debug("Docker unavailable: %s", exc)
        return {"available": False, "containers": [], "message": str(exc)}


def _check_url_once(url, timeout=5):
    start = time.perf_counter()
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        if resp.status_code >= 400:
            resp = requests.get(url, timeout=timeout, allow_redirects=True)
        ms = int((time.perf_counter() - start) * 1000)
        return resp.status_code < 500, ms, ""
    except Exception as exc:
        ms = int((time.perf_counter() - start) * 1000)
        return False, ms, str(exc)[:200]


def _check_url(url, timeout=5):
    is_up, ms, err = _check_url_once(url, timeout)
    if is_up:
        return is_up, ms, err
    is_up2, ms2, err2 = _check_url_once(url, timeout)
    if is_up2:
        return True, ms + ms2, ""
    return False, ms2, err2 or err


def _has_open_down_alert(service):
    return Alert.objects.filter(
        service=service,
        level="error",
        title=f"{service.name} is down",
        acknowledged=False,
    ).exists()


def _should_send_recovery(service):
    down = (
        Alert.objects.filter(
            service=service,
            level="error",
            title=f"{service.name} is down",
        )
        .order_by("-created_at")
        .first()
    )
    if not down:
        return False
    return not Alert.objects.filter(
        service=service,
        level="success",
        created_at__gt=down.created_at,
    ).exists()


def run_health_checks():
    if not settings.HEALTH_CHECK_ENABLED:
        return []
    results = []
    for service in Service.objects.filter(enabled=True):
        url = service.health_check_url or service.href
        if not url:
            continue
        prev = (
            ServiceCheck.objects.filter(service=service).order_by("-checked_at").first()
        )
        if prev and (timezone.now() - prev.checked_at).total_seconds() < CHECK_THROTTLE_SECONDS:
            results.append(
                {
                    "id": service.id,
                    "name": service.name,
                    "is_up": prev.is_up,
                    "response_ms": prev.response_ms,
                    "error": prev.error,
                }
            )
            continue

        is_up, ms, err = _check_url(url)
        ServiceCheck.objects.create(
            service=service, is_up=is_up, response_ms=ms, error=err
        )

        if prev and prev.is_up and not is_up:
            pass
        elif prev and not prev.is_up and not is_up:
            if not _has_open_down_alert(service):
                Alert.objects.create(
                    service=service,
                    level="error",
                    title=f"{service.name} is down",
                    message=err or "Health check failed",
                )
                log_audit(
                    "service_down",
                    message=f"{service.name} down",
                    service=service.name,
                )
                send_ntfy(f"DOWN: {service.name}", err or service.href)
        elif prev and not prev.is_up and is_up:
            if _should_send_recovery(service):
                Alert.objects.create(
                    service=service,
                    level="success",
                    title=f"{service.name} recovered",
                    message="Service is responding again",
                )
                log_audit(
                    "service_up", message=f"{service.name} up", service=service.name
                )

        results.append(
            {
                "id": service.id,
                "name": service.name,
                "is_up": is_up,
                "response_ms": ms,
                "error": err,
            }
        )
    return results


def send_ntfy(title, message=""):
    if not settings.NTFY_URL:
        return False
    url = urljoin(settings.NTFY_URL.rstrip("/") + "/", settings.NTFY_TOPIC)
    auth = None
    if settings.NTFY_USER and settings.NTFY_PASSWORD:
        auth = (settings.NTFY_USER, settings.NTFY_PASSWORD)
    try:
        requests.post(
            url,
            data=message or title,
            headers={"Title": title[:250]},
            auth=auth,
            timeout=10,
        )
        return True
    except Exception as exc:
        logger.warning("ntfy failed: %s", exc)
        return False


def service_status_map():
    data = {}
    for service in Service.objects.filter(enabled=True):
        last = service.checks.order_by("-checked_at").first()
        data[service.id] = {
            "is_up": last.is_up if last else None,
            "response_ms": last.response_ms if last else None,
        }
    return data


def uptime_sparkline(service, hours=24):
    since = timezone.now() - timezone.timedelta(hours=hours)
    checks = list(
        service.checks.filter(checked_at__gte=since)
        .order_by("checked_at")
        .values("is_up", "checked_at")
    )
    if not checks:
        return []
    step = max(1, len(checks) // 24)
    sampled = checks[::step][-24:]
    return [
        {"up": c["is_up"], "at": c["checked_at"].isoformat()} for c in sampled
    ]


WIDGET_CACHE_TTL = 60
WEATHER_CACHE_TTL = 900
WEATHER_API_URL = "https://api.open-meteo.com/v1/forecast"


def _widget_cache_key(widget_type, url, key=""):
    return f"widget:{widget_type}:{url}:{key}"


def _fetch_pihole_stats(base_url, api_key):
    base = base_url.rstrip("/")
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        resp = requests.get(f"{base}/api/stats/summary", headers=headers, timeout=8)
        if resp.ok:
            data = resp.json()
            queries = data.get("queries", {})
            gravity = data.get("gravity", {})
            blocked = queries.get("blocked", 0)
            total = queries.get("total", 0)
            percent = queries.get("percent_blocked", 0)
            if not total and blocked:
                percent = round(100 * blocked / max(blocked + queries.get("forwarded", 0), 1), 1)
            return {
                "stats": [
                    {"label": "QUERIES", "value": f"{total:,}"},
                    {"label": "BLOCKED", "value": f"{blocked:,} ({percent}%)"},
                    {
                        "label": "GRAVITY",
                        "value": f"{gravity.get('domains_being_blocked', 0):,}",
                    },
                ],
            }
    except Exception as exc:
        logger.debug("Pi-hole v6 API failed: %s", exc)

    if api_key:
        try:
            resp = requests.get(
                f"{base}/admin/api.php",
                params={"summaryRaw": "", "auth": api_key},
                timeout=8,
            )
            if resp.ok:
                data = resp.json()
                queries = data.get("dns_queries_today", data.get("dns_queries", 0))
                blocked = data.get("ads_blocked_today", data.get("ads_blocked", 0))
                percent = data.get("ads_percentage_today", data.get("ads_percentage", 0))
                gravity = data.get("domains_being_blocked", data.get("gravity", 0))
                return {
                    "stats": [
                        {"label": "QUERIES", "value": f"{queries:,}"},
                        {"label": "BLOCKED", "value": f"{blocked:,} ({percent}%)"},
                        {"label": "GRAVITY", "value": f"{gravity:,}"},
                    ],
                }
        except Exception as exc:
            logger.debug("Pi-hole v5 API failed: %s", exc)
    return {"error": "Pi-hole API unavailable"}


def _fetch_speedtest_stats(base_url, api_key):
    base = base_url.rstrip("/")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    endpoints = [
        "/api/speedtest/latest",
        "/api/speedtest/recent",
        "/api/results/latest",
    ]
    for endpoint in endpoints:
        try:
            resp = requests.get(f"{base}{endpoint}", headers=headers, timeout=8)
            if not resp.ok:
                continue
            payload = resp.json()
            data = payload.get("data", payload)
            if isinstance(data, list):
                data = data[0] if data else {}
            download = data.get("download") or data.get("download_bits")
            upload = data.get("upload") or data.get("upload_bits")
            ping = data.get("ping") or data.get("latency")
            if download is None:
                continue
            download_mbps = download / 1_000_000 if download > 1000 else download
            upload_mbps = upload / 1_000_000 if upload and upload > 1000 else upload
            stats = [
                {"label": "DOWNLOAD", "value": f"{download_mbps:.0f} Mbit/s"},
            ]
            if upload_mbps:
                stats.append({"label": "UPLOAD", "value": f"{upload_mbps:.0f} Mbit/s"})
            if ping:
                stats.append({"label": "PING", "value": f"{ping:.0f} ms"})
            return {"stats": stats}
        except Exception as exc:
            logger.debug("Speedtest endpoint %s failed: %s", endpoint, exc)
    return {"error": "Speedtest API unavailable"}


def fetch_service_widget(service):
    if service.widget_type == Service.WidgetType.NONE:
        return None
    url = service.widget_url or service.href
    if not url:
        return {"error": "No widget URL configured"}
    cache_key = _widget_cache_key(service.widget_type, url, service.widget_api_key)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    if service.widget_type == Service.WidgetType.PIHOLE:
        result = _fetch_pihole_stats(url, service.widget_api_key)
    elif service.widget_type == Service.WidgetType.SPEEDTEST:
        result = _fetch_speedtest_stats(url, service.widget_api_key)
    else:
        result = {"error": "Unknown widget type"}
    cache.set(cache_key, result, WIDGET_CACHE_TTL)
    return result


def fetch_all_widgets():
    widgets = {}
    for service in Service.objects.filter(enabled=True).exclude(
        widget_type=Service.WidgetType.NONE
    ):
        widgets[str(service.id)] = {
            "type": service.widget_type,
            "data": fetch_service_widget(service),
        }
    return widgets


WEATHER_CODE_LABELS = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Foggy",
    51: "Drizzle",
    53: "Drizzle",
    55: "Drizzle",
    61: "Rain",
    63: "Rain",
    65: "Rain",
    71: "Snow",
    73: "Snow",
    75: "Snow",
    80: "Showers",
    81: "Showers",
    82: "Showers",
    95: "Storm",
    96: "Storm",
    99: "Storm",
}


def fetch_weather():
    site = get_site_settings()
    if not site.weather_location or not site.weather_lat or not site.weather_lon:
        return {"configured": False}
    cache_key = f"weather:{site.weather_lat}:{site.weather_lon}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            WEATHER_API_URL,
            params={
                "latitude": site.weather_lat,
                "longitude": site.weather_lon,
                "current": "temperature_2m,weather_code,is_day",
                "timezone": "auto",
            },
            timeout=10,
        )
        resp.raise_for_status()
        current = resp.json().get("current", {})
        code = current.get("weather_code", 0)
        result = {
            "configured": True,
            "location": site.weather_location,
            "temperature_c": current.get("temperature_2m"),
            "weather_code": code,
            "label": WEATHER_CODE_LABELS.get(code, "Weather"),
            "is_day": current.get("is_day", 1),
        }
        cache.set(cache_key, result, WEATHER_CACHE_TTL)
        return result
    except Exception as exc:
        logger.warning("Weather fetch failed: %s", exc)
        return {
            "configured": True,
            "location": site.weather_location,
            "error": str(exc)[:120],
        }
