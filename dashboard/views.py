import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.models import AuditEvent

from .models import Alert, Bookmark, Service, ServiceCategory
from . import services


@login_required
def dashboard_view(request):
    categories = ServiceCategory.objects.prefetch_related("services").all()
    bookmarks = Bookmark.objects.filter(enabled=True)
    alerts = Alert.objects.all()[:20]
    status = services.service_status_map()
    recent_logins = AuditEvent.objects.filter(event_type="login")[:8]
    services_up = sum(1 for s in status.values() if s.get("is_up") is True)
    services_down = sum(1 for s in status.values() if s.get("is_up") is False)
    services_unknown = sum(1 for s in status.values() if s.get("is_up") is None)
    unack_alerts = Alert.objects.filter(acknowledged=False).count()
    down_category_ids = set()
    for cat in categories:
        for svc in cat.services.all():
            if svc.enabled and status.get(svc.id, {}).get("is_up") is False:
                down_category_ids.add(cat.id)
                break
    return render(
        request,
        "dashboard/index.html",
        {
            "categories": categories,
            "bookmarks": bookmarks,
            "alerts": alerts,
            "status": status,
            "recent_logins": recent_logins,
            "services_up": services_up,
            "services_down": services_down,
            "services_unknown": services_unknown,
            "unack_alerts": unack_alerts,
            "down_category_ids": down_category_ids,
        },
    )


@login_required
@require_GET
def api_system(request):
    return JsonResponse(services.get_system_stats())


@login_required
@require_GET
def api_docker(request):
    return JsonResponse(services.get_docker_containers())


@login_required
@require_GET
def api_health(request):
    return JsonResponse({"services": services.run_health_checks()})


@login_required
@require_GET
def api_alerts(request):
    alerts = list(
        Alert.objects.all()[:30].values(
            "id", "created_at", "level", "title", "message", "acknowledged"
        )
    )
    return JsonResponse({"alerts": alerts})


@login_required
@require_POST
def api_alerts_ack(request):
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        body = {}
    alert_id = body.get("id")
    if alert_id:
        updated = Alert.objects.filter(id=alert_id, acknowledged=False).update(
            acknowledged=True
        )
    else:
        updated = Alert.objects.filter(acknowledged=False).update(acknowledged=True)
    unack = Alert.objects.filter(acknowledged=False).count()
    return JsonResponse({"ok": True, "updated": updated, "unacknowledged": unack})


@login_required
@require_GET
def api_uptime(request):
    data = {}
    for svc in Service.objects.filter(enabled=True):
        bars = services.uptime_sparkline(svc)
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
    return JsonResponse({"uptime": data})


@login_required
@require_GET
def api_widgets(request):
    return JsonResponse({"widgets": services.fetch_all_widgets()})


@login_required
@require_GET
def api_weather(request):
    return JsonResponse(services.fetch_weather())
