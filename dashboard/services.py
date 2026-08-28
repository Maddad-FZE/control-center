import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
SYSTEM_CACHE_TTL = 8
DOCKER_CACHE_TTL = 15
HEALTH_CACHE_TTL = CHECK_THROTTLE_SECONDS
UPTIME_CACHE_TTL = 25
ALERTS_CACHE_TTL = 5
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
    cached = cache.get("system:stats")
    if cached is not None:
        return cached
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
    result = {
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
    cache.set("system:stats", result, SYSTEM_CACHE_TTL)
    return result


def get_docker_containers():
    cached = cache.get("docker:containers")
    if cached is not None:
        return cached
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
        result = {"available": True, "containers": out}
        cache.set("docker:containers", result, DOCKER_CACHE_TTL)
        return result
    except Exception as exc:
        logger.debug("Docker unavailable: %s", exc)
        result = {"available": False, "containers": [], "message": str(exc)}
        cache.set("docker:containers", result, DOCKER_CACHE_TTL)
        return result


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
    cached = cache.get("health:results")
    if cached is not None:
        return cached
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
    cache.set("health:results", results, HEALTH_CACHE_TTL)
    return results


def get_cached_alerts(limit=30):
    cached = cache.get("alerts:recent")
    if cached is not None:
        return cached
    alerts = list(
        Alert.objects.all()[:limit].values(
            "id", "created_at", "level", "title", "message", "acknowledged"
        )
    )
    cache.set("alerts:recent", alerts, ALERTS_CACHE_TTL)
    return alerts


def get_cached_uptime_payload():
    cached = cache.get("uptime:payload")
    if cached is not None:
        return cached
    data = {}
    for svc in Service.objects.filter(enabled=True):
        bars = uptime_sparkline(svc)
        since = timezone.now() - timezone.timedelta(hours=24)
        checks = list(
            svc.checks.filter(checked_at__gte=since).values_list("is_up", flat=True)
        )
        percent = round(100 * sum(checks) / len(checks), 1) if checks else None
        data[str(svc.id)] = {
            "name": svc.name,
            "percent": percent,
            "bars": bars,
        }
    payload = {"uptime": data}
    cache.set("uptime:payload", payload, UPTIME_CACHE_TTL)
    return payload


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


WIDGET_CACHE_TTL = 45
WIDGET_STALE_TTL = 3600
WIDGET_BUNDLE_TTL = 30
WIDGET_BUNDLE_STALE_TTL = 3600
WEATHER_CACHE_TTL = 900
WEATHER_API_URL = "https://api.open-meteo.com/v1/forecast"


def _widget_cache_key(widget_type, url, key=""):
    return f"widget:{widget_type}:{url}:{key}"


def _set_widget_cache(cache_key, result):
    cache.set(cache_key, result, WIDGET_CACHE_TTL)
    if result and "error" not in result:
        cache.set(f"{cache_key}:stale", result, WIDGET_STALE_TTL)


def _get_widget_stale(cache_key):
    return cache.get(f"{cache_key}:stale")


def _pihole_sid_cache_key(base, api_key):
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return f"pihole:sid:{base}:{digest}"


def _pihole_authenticate(base, api_key):
    """Pi-hole v6 session login; returns (sid, error_message)."""
    cache_key = _pihole_sid_cache_key(base, api_key)
    cached = cache.get(cache_key)
    if cached:
        return cached, ""

    try:
        resp = requests.post(
            f"{base}/api/auth",
            json={"password": api_key},
            timeout=8,
        )
    except Exception as exc:
        logger.debug("Pi-hole v6 auth failed: %s", exc)
        return None, "Pi-hole login request failed"

    if resp.status_code == 401:
        return None, "Pi-hole login failed — check app password"
    if not resp.ok:
        return None, f"Pi-hole login returned {resp.status_code}"

    try:
        data = resp.json()
    except ValueError:
        return None, "Pi-hole login returned invalid JSON"

    session = data.get("session") or {}
    sid = session.get("sid") or data.get("sid")
    if not sid:
        return None, "Pi-hole login did not return a session"

    validity = session.get("validity") or data.get("validity") or 300
    try:
        ttl = int(validity)
    except (TypeError, ValueError):
        ttl = 300
    cache.set(cache_key, sid, max(60, min(ttl - 30, 3600)))
    return sid, ""


def _pihole_summary_stats(data):
    queries = data.get("queries", {})
    gravity = data.get("gravity", {})
    blocked = queries.get("blocked", 0)
    total = queries.get("total", 0)
    percent = queries.get("percent_blocked", 0)
    if isinstance(percent, float):
        percent = round(percent, 1)
    if not total and blocked:
        percent = round(
            100 * blocked / max(blocked + queries.get("forwarded", 0), 1), 1
        )
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


def _fetch_pihole_stats(base_url, api_key):
    base = base_url.rstrip("/")

    if api_key:
        sid, auth_error = _pihole_authenticate(base, api_key)
        if sid:
            try:
                resp = requests.get(
                    f"{base}/api/stats/summary",
                    headers={"X-FTL-SID": sid},
                    timeout=8,
                )
                if resp.ok:
                    return _pihole_summary_stats(resp.json())
                if resp.status_code in (401, 403):
                    cache.delete(_pihole_sid_cache_key(base, api_key))
                logger.debug(
                    "Pi-hole v6 summary failed after auth: %s", resp.status_code
                )
            except Exception as exc:
                logger.debug("Pi-hole v6 summary failed: %s", exc)
        elif auth_error:
            return {"error": auth_error}

    try:
        resp = requests.get(f"{base}/api/stats/summary", timeout=8)
        if resp.status_code == 401:
            return {
                "error": "Pi-hole API requires an app password (Web Interface / API → Configure app password)",
            }
        if resp.status_code == 403:
            return {"error": "Pi-hole API returned 403"}
        if resp.ok:
            return _pihole_summary_stats(resp.json())
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


def _resolve_json_path(data, path):
    if not path:
        return None
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if idx < len(current) else None
        else:
            return None
    return current


def _format_metric_value(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        if abs(value) >= 1000:
            return f"{value:,.0f}"
        return f"{value:.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _fetch_generic_metrics(service):
    url = service.widget_url or service.build_href()
    if not url:
        return {"error": "No API URL configured"}
    cache_key = _widget_cache_key("generic", url, service.widget_api_key)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    headers = {}
    if service.widget_api_key:
        headers["X-API-Key"] = service.widget_api_key
        headers["Authorization"] = f"Bearer {service.widget_api_key}"
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if not resp.ok:
            return {"error": f"API returned {resp.status_code}"}
        payload = resp.json()
        data = payload.get("data", payload)
        if isinstance(data, list) and data:
            data = data[0]
        stats = []
        for metric in service.metrics.all():
            raw = _resolve_json_path(data, metric.json_path)
            if metric.label.upper() == "BLOCKED" and isinstance(raw, (int, float)):
                total = _resolve_json_path(data, "queries.total") or _resolve_json_path(
                    data, "dns_queries_today"
                )
                if total:
                    pct = round(100 * raw / total, 1)
                    value = f"{raw:,} ({pct}%)"
                else:
                    value = _format_metric_value(raw)
            elif metric.json_path == "download" and isinstance(raw, (int, float)):
                mbps = raw / 1_000_000 if raw > 1000 else raw
                value = f"{mbps:.0f} Mbit/s"
            elif metric.json_path == "upload" and isinstance(raw, (int, float)):
                mbps = raw / 1_000_000 if raw > 1000 else raw
                value = f"{mbps:.0f} Mbit/s"
            elif metric.json_path == "ping" and isinstance(raw, (int, float)):
                value = f"{raw:.0f} ms"
            else:
                value = _format_metric_value(raw)
            stats.append({"label": metric.label, "value": value})
        result = {"stats": stats} if stats else {"error": "No metrics configured"}
        if "error" in result:
            stale = _get_widget_stale(cache_key)
            if stale:
                return stale
        _set_widget_cache(cache_key, result)
        return result
    except Exception as exc:
        logger.debug("Generic widget fetch failed: %s", exc)
        stale = _get_widget_stale(cache_key)
        if stale:
            return stale
        return {"error": "API unavailable"}


def fetch_service_widget(service):
    url = service.widget_url or service.build_href()
    if service.widget_type == Service.WidgetType.PIHOLE:
        if not url:
            return {"error": "No widget URL configured"}
        cache_key = _widget_cache_key(service.widget_type, url, service.widget_api_key)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        result = _fetch_pihole_stats(url, service.widget_api_key)
        if "error" in result:
            stale = _get_widget_stale(cache_key)
            if stale:
                return stale
        _set_widget_cache(cache_key, result)
        return result

    if service.widget_type == Service.WidgetType.SPEEDTEST:
        if not url:
            return {"error": "No widget URL configured"}
        cache_key = _widget_cache_key(service.widget_type, url, service.widget_api_key)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        result = _fetch_speedtest_stats(url, service.widget_api_key)
        if "error" in result:
            stale = _get_widget_stale(cache_key)
            if stale:
                return stale
        _set_widget_cache(cache_key, result)
        return result

    metrics = list(service.metrics.all())
    if metrics:
        return _fetch_generic_metrics(service)
    if service.widget_type == Service.WidgetType.NONE:
        return None
    if not url:
        return {"error": "No widget URL configured"}
    cache_key = _widget_cache_key(service.widget_type, url, service.widget_api_key)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = {"error": "Unknown widget type"}
    cache.set(cache_key, result, WIDGET_CACHE_TTL)
    return result


def fetch_all_widgets(public_only=False):
    bundle_key = f"widgets:bundle:{public_only}"
    stale_key = f"{bundle_key}:stale"
    cached = cache.get(bundle_key)
    if cached is not None:
        return cached

    qs = list(
        Service.objects.filter(enabled=True).prefetch_related("metrics")
    )
    if public_only:
        qs = [s for s in qs if s.is_public]

    widgets = {}

    def _fetch_one(service):
        data = fetch_service_widget(service)
        if data is None:
            return None
        return str(service.id), {
            "type": service.widget_type,
            "data": data,
        }

    if qs:
        workers = min(8, len(qs))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_fetch_one, svc) for svc in qs]
            for future in as_completed(futures):
                try:
                    row = future.result()
                    if row:
                        sid, entry = row
                        widgets[sid] = entry
                except Exception as exc:
                    logger.warning("Widget worker failed: %s", exc)

    if not widgets:
        stale_bundle = cache.get(stale_key)
        if stale_bundle:
            return stale_bundle

    cache.set(bundle_key, widgets, WIDGET_BUNDLE_TTL)
    if widgets:
        cache.set(stale_key, widgets, WIDGET_BUNDLE_STALE_TTL)
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
