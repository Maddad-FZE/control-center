import json

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET, require_POST

from core.models import AuditEvent, log_audit

from library.catalog import LIBRARY_DESCRIPTIONS, get_service_by_slug
from library.icons import icon_url_for_entry
from library.installer import services_host
from library.models import InstalledService
from library.versions import maybe_check_daily, update_map_for_services

from .forms import ServiceForm, ServiceMetricFormSet
from .models import Alert, Bookmark, Service, ServiceCategory
from .presets import apply_preset_metrics
from . import services


def _is_guest(request):
    return not request.user.is_authenticated


def _filter_categories_for_request(request):
    categories = ServiceCategory.objects.prefetch_related(
        "services", "services__metrics"
    ).all()
    if _is_guest(request):
        filtered = []
        for cat in categories:
            public_services = [
                s for s in cat.services.all() if s.enabled and s.is_public
            ]
            if public_services:
                cat.filtered_services = public_services
                filtered.append(cat)
        return filtered
    result = []
    for cat in categories:
        enabled = [s for s in cat.services.all() if s.enabled]
        if enabled:
            cat.filtered_services = enabled
            result.append(cat)
    return result


def _status_for_services(service_ids):
    all_status = services.service_status_map()
    if not service_ids:
        return {}
    return {sid: all_status.get(sid) for sid in service_ids}


@login_not_required
def dashboard_view(request):
    if request.user.is_authenticated and request.user.is_superuser:
        maybe_check_daily()

    categories = _filter_categories_for_request(request)
    is_guest = _is_guest(request)
    is_admin = request.user.is_authenticated and request.user.is_superuser

    service_ids = []
    for cat in categories:
        for svc in cat.filtered_services:
            service_ids.append(svc.id)

    status = _status_for_services(service_ids)
    service_updates = {}
    if is_admin:
        all_services = []
        for cat in categories:
            all_services.extend(cat.filtered_services)
        service_updates = update_map_for_services(all_services)

    tracked_services = []
    app_services = []
    misc_services = []
    down_section_ids = set()
    for cat in categories:
        for svc in cat.filtered_services:
            if svc.is_misc:
                misc_services.append(svc)
                bucket = "misc"
            elif svc.has_widget:
                tracked_services.append(svc)
                bucket = "tracked"
            else:
                app_services.append(svc)
                bucket = "apps"
            if status.get(svc.id, {}).get("is_up") is False:
                down_section_ids.add(bucket)

    bookmarks = Bookmark.objects.filter(enabled=True) if not is_guest else []

    visible_status = [row for row in status.values() if row]
    context = {
        "tracked_services": tracked_services,
        "app_services": app_services,
        "misc_services": misc_services,
        "bookmarks": bookmarks,
        "status": status,
        "is_guest": is_guest,
        "is_admin": is_admin,
        "down_section_ids": down_section_ids,
        "categories_list": ServiceCategory.objects.order_by("sort_order", "name"),
        "service_updates": service_updates,
        "services_up": sum(1 for row in visible_status if row.get("is_up") is True),
        "services_down": sum(1 for row in visible_status if row.get("is_up") is False),
        "services_unknown": sum(1 for row in visible_status if row.get("is_up") is None),
        "unack_alerts": 0,
    }

    if not is_guest:
        alerts = Alert.objects.all()[:20]
        recent_logins = AuditEvent.objects.filter(event_type="login")[:8]
        full_status = services.service_status_map()
        services_up = sum(1 for s in full_status.values() if s.get("is_up") is True)
        services_down = sum(1 for s in full_status.values() if s.get("is_up") is False)
        services_unknown = sum(1 for s in full_status.values() if s.get("is_up") is None)
        unack_alerts = Alert.objects.filter(acknowledged=False).count()
        context.update(
            {
                "alerts": alerts,
                "recent_logins": recent_logins,
                "services_up": services_up,
                "services_down": services_down,
                "services_unknown": services_unknown,
                "unack_alerts": unack_alerts,
            }
        )

    return render(request, "dashboard/index.html", context)


@login_required
def service_create_view(request):
    if not request.user.is_superuser:
        return redirect("dashboard")
    catalog_slug = (request.GET.get("catalog") or request.POST.get("catalog_slug") or "").strip()
    catalog_entry = get_service_by_slug(catalog_slug) if catalog_slug else None
    installed_without_cards = []
    if request.method == "GET":
        card_slugs = set(
            Service.objects.exclude(catalog_slug="").values_list("catalog_slug", flat=True)
        )
        for inst in InstalledService.objects.filter(
            status__in=("running", "stopped")
        ):
            if inst.slug not in card_slugs:
                entry = get_service_by_slug(inst.slug)
                if entry:
                    installed_without_cards.append(
                        {
                            "slug": inst.slug,
                            "name": entry["name"],
                            "icon": icon_url_for_entry(inst.slug, entry.get("icon", "")),
                            "host_port": inst.host_port,
                        }
                    )
    if request.method == "POST":
        form = ServiceForm(request.POST, request.FILES, request=request)
        metric_formset = ServiceMetricFormSet(request.POST, prefix="metrics")
        if form.is_valid():
            svc = form.save()
            preset = form.cleaned_data.get("preset", "none")
            if preset != "none":
                apply_preset_metrics(svc, preset)
                log_audit(
                    "admin",
                    request=request,
                    user=request.user,
                    message=f"Created card {svc.name}",
                )
                messages.success(request, f"Card “{svc.name}” created.")
                return redirect("dashboard")
            metric_formset = ServiceMetricFormSet(
                request.POST, instance=svc, prefix="metrics"
            )
            if metric_formset.is_valid():
                metric_formset.save()
                log_audit(
                    "admin",
                    request=request,
                    user=request.user,
                    message=f"Created card {svc.name}",
                )
                messages.success(request, f"Card “{svc.name}” created.")
                return redirect("dashboard")
    else:
        initial = {}
        preset = "none"
        if catalog_entry:
            host = services_host(request)
            port = catalog_entry.get("default_port")
            installed = InstalledService.objects.filter(
                slug=catalog_slug, status__in=("running", "stopped")
            ).first()
            if installed and installed.host_port:
                port = installed.host_port
            initial = {
                "name": catalog_entry["name"],
                "description": LIBRARY_DESCRIPTIONS.get(catalog_slug)
                or catalog_entry.get("tagline", ""),
                "icon": catalog_entry.get("icon", ""),
                "host": host,
                "port": port,
                "path": catalog_entry.get("path", "/"),
                "widget_type": catalog_entry.get("widget_type", "none"),
                "catalog_slug": catalog_slug,
            }
            widget_type = catalog_entry.get("widget_type", "none")
            if widget_type == "pihole":
                preset = "pihole"
            elif widget_type == "speedtest":
                preset = "speedtest"
        form = ServiceForm(initial=initial, request=request)
        if preset != "none":
            form.fields["preset"].initial = preset
        metric_formset = ServiceMetricFormSet(prefix="metrics")
    return render(
        request,
        "dashboard/service_form.html",
        {
            "form": form,
            "metric_formset": metric_formset,
            "is_new": True,
            "catalog_entry": catalog_entry,
            "installed_without_cards": installed_without_cards,
            "link_meta": form.link_meta,
        },
    )


@login_required
def service_edit_view(request, service_id):
    if not request.user.is_superuser:
        return redirect("dashboard")
    service = get_object_or_404(Service, pk=service_id)
    form = ServiceForm(instance=service, request=request)
    metric_formset = ServiceMetricFormSet(instance=service, prefix="metrics")
    if request.method == "POST":
        form = ServiceForm(request.POST, request.FILES, instance=service, request=request)
        metric_formset = ServiceMetricFormSet(
            request.POST, instance=service, prefix="metrics"
        )
        if form.is_valid() and metric_formset.is_valid():
            svc = form.save()
            preset = form.cleaned_data.get("preset", "none")
            if preset != "none":
                svc.metrics.all().delete()
                apply_preset_metrics(svc, preset)
            metric_formset.save()
            log_audit("admin", request=request, user=request.user, message=f"Updated card {svc.name}")
            messages.success(request, f"Card “{svc.name}” updated.")
            return redirect("dashboard")
    return render(
        request,
        "dashboard/service_form.html",
        {
            "form": form,
            "metric_formset": metric_formset,
            "is_new": False,
            "service": service,
            "link_meta": form.link_meta,
        },
    )


@login_required
@require_POST
def api_service_visibility(request, service_id):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    service = get_object_or_404(Service, pk=service_id)
    service.is_public = not service.is_public
    service.save(update_fields=["is_public"])
    log_audit(
        "admin",
        request=request,
        user=request.user,
        message=f"{service.name} set to {'public' if service.is_public else 'private'}",
    )
    return JsonResponse({"ok": True, "is_public": service.is_public})


@login_required
@require_POST
def api_service_delete(request, service_id):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    service = get_object_or_404(Service, pk=service_id)
    name = service.name
    service.delete()
    log_audit("admin", request=request, user=request.user, message=f"Deleted card {name}")
    return JsonResponse({"ok": True})


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
    return JsonResponse({"alerts": services.get_cached_alerts(limit=30)})


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
    cache.delete("alerts:recent")
    unack = Alert.objects.filter(acknowledged=False).count()
    return JsonResponse({"ok": True, "updated": updated, "unacknowledged": unack})


@login_required
@require_GET
def api_uptime(request):
    return JsonResponse(services.get_cached_uptime_payload())


@login_not_required
@require_GET
def api_widgets(request):
    public_only = not request.user.is_authenticated
    return JsonResponse({"widgets": services.fetch_all_widgets(public_only=public_only)})


@login_required
@require_GET
def api_icons(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    from .icon_library import icon_url, search_simpleicons

    query = (request.GET.get("q") or "").strip()
    icons = [
        {"title": row["title"], "slug": row["slug"], "url": icon_url(row["slug"])}
        for row in search_simpleicons(query, limit=420)
    ]
    return JsonResponse({"icons": icons})


@login_not_required
@require_GET
def api_weather(request):
    if not request.user.is_authenticated:
        return JsonResponse({"configured": False})
    return JsonResponse(services.fetch_weather())
