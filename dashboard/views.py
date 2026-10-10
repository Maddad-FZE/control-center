import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET, require_POST

from core.models import AuditEvent, log_audit

from library.catalog import get_service_by_slug
from library.icons import icon_url_for_entry
from library.installer import services_host
from library.models import InstalledService
from library.pihole import attach_launch_href
from library.versions import update_map_for_services

from .forms import ServiceForm, ServiceMetricFormSet
from .models import Alert, DebugIncident, Service, ServiceCategory
from .prefs import open_in_new_tab_ids, prefers_new_tab, set_open_in_new_tab
from .presets import apply_preset_metrics
from . import hostops, services

logger = logging.getLogger(__name__)


def _is_guest(request):
    return not request.user.is_authenticated


def _open_tab_ids(user):
    ids = set(open_in_new_tab_ids(user))
    ids.update(
        Service.objects.filter(catalog_slug="uptime-kuma").values_list("id", flat=True)
    )
    return ids


def _apply_publish_urls(service, by_id=None, by_slug=None):
    from library.cloudflare import hostname_for_service, public_href

    hostname = hostname_for_service(service, by_id=by_id, by_slug=by_slug)
    lan = service.href or service.build_href()
    public = public_href(hostname, lan) if hostname else ""
    service.published_hostname = hostname
    service.lan_href = lan
    service.public_href = public
    service.open_href = public or lan
    return service


def _filter_categories_for_request(request):
    from core.access import visible_service_ids

    categories = ServiceCategory.objects.prefetch_related(
        "services", "services__metrics"
    ).all()
    allowed = visible_service_ids(request.user if request.user.is_authenticated else None)
    filtered = []
    for cat in categories:
        visible = [s for s in cat.services.all() if s.enabled and s.id in allowed]
        if visible:
            cat.filtered_services = visible
            filtered.append(cat)
    return filtered


@login_not_required
def dashboard_view(request):
    categories = _filter_categories_for_request(request)
    is_guest = _is_guest(request)
    is_admin = request.user.is_authenticated and request.user.is_superuser

    service_ids = []
    for cat in categories:
        for svc in cat.filtered_services:
            service_ids.append(svc.id)

    all_status = services.service_status_map()
    status = {sid: all_status.get(sid) for sid in service_ids} if service_ids else {}
    service_updates = {}
    if is_admin:
        all_services = []
        for cat in categories:
            all_services.extend(cat.filtered_services)
        service_updates = update_map_for_services(all_services)

    published_by_id = {}
    published_by_slug = {}
    containers_by_slug = {}
    tunnel_linked = False
    tunnel_zone = ""
    try:
        from core.models import SiteSettings
        from library.cloudflare import published_hostname_maps, tunnel_is_linked

        published_by_id, published_by_slug = published_hostname_maps()
        if is_admin:
            tunnel_linked = tunnel_is_linked()
            tunnel_zone = SiteSettings.load().cf_zone_name
            containers_by_slug = {
                row.slug: row.container_name
                for row in InstalledService.objects.exclude(container_name="")
            }
    except Exception:
        tunnel_linked = False

    tracked_services = []
    app_services = []
    misc_services = []
    down_section_ids = set()
    for cat in categories:
        for svc in cat.filtered_services:
            _apply_publish_urls(svc, published_by_id, published_by_slug)
            attach_launch_href(request, svc)
            svc.container_name = containers_by_slug.get(svc.catalog_slug, "")
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

    app_services.sort(key=lambda s: (s.sort_order, s.name.lower()))

    visible_status = [row for row in status.values() if row]
    context = {
        "tracked_services": tracked_services,
        "app_services": app_services,
        "misc_services": misc_services,
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
        "open_in_new_tab_ids": _open_tab_ids(request.user),
        "tunnel_linked": tunnel_linked,
        "tunnel_zone": tunnel_zone,
    }

    if not is_guest:
        alerts = Alert.objects.all()[:20]
        recent_logins = AuditEvent.objects.filter(event_type="login")[:8]
        services_up = sum(1 for s in all_status.values() if s.get("is_up") is True)
        services_down = sum(1 for s in all_status.values() if s.get("is_up") is False)
        services_unknown = sum(1 for s in all_status.values() if s.get("is_up") is None)
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


def _visible_service(request, service_id):
    from core.access import can_open_service

    service = get_object_or_404(Service, pk=service_id, enabled=True)
    user = request.user if request.user.is_authenticated else None
    if not can_open_service(user, service):
        return None
    return service


@login_not_required
def service_view(request, service_id):
    service = _visible_service(request, service_id)
    if service is None:
        return redirect("dashboard")
    _apply_publish_urls(service)
    attach_launch_href(request, service)
    href = service.open_href
    if not href:
        return redirect("dashboard")
    return render(
        request,
        "dashboard/service_view.html",
        {
            "service": service,
            "service_href": href,
            "launch_href": service.launch_href,
            "lan_href": service.lan_href,
            "open_in_new_tab": prefers_new_tab(request.user, service.id),
            "is_guest": _is_guest(request),
        },
    )


@login_not_required
def service_launch_view(request, service_id):
    from library import pihole as pihole_setup

    service = _visible_service(request, service_id)
    if service is None:
        return redirect("dashboard")
    _apply_publish_urls(service)
    target = pihole_setup.browser_url(request, service) or service.open_href
    if not target:
        return redirect("dashboard")
    if _is_guest(request) or not pihole_setup.supports_autologin(service):
        return redirect(service.open_href or target)

    password = pihole_setup.ensure_password(service, request.user)
    if not password:
        return redirect(service.open_href or target)

    base = pihole_setup.auth_base(service)
    sid, error = ("", "")
    if base:
        sid, error = services._pihole_authenticate(base, password)
    if not sid:
        logger.debug("Pi-hole auto-login skipped: %s", error)
        return redirect(service.open_href or target)

    response = redirect(target)
    response.set_cookie(
        "sid",
        sid,
        path="/",
        samesite="Lax",
        secure=request.is_secure(),
        httponly=False,
        max_age=1800,
    )
    return response


@login_required
@require_POST
def api_service_open_pref(request, service_id):
    service = _visible_service(request, service_id)
    if service is None:
        return JsonResponse({"error": "Not found"}, status=404)
    try:
        payload = json.loads(request.body.decode() or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        payload = {}
    enabled = bool(payload.get("open_in_new_tab"))
    set_open_in_new_tab(request.user, service.id, enabled)
    return JsonResponse({"ok": True, "open_in_new_tab": enabled})


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
                "description": catalog_entry.get("description")
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
    try:
        from dashboard.kuma import delete_monitor_for_service

        delete_monitor_for_service(service)
    except Exception:
        pass
    service.delete()
    log_audit("admin", request=request, user=request.user, message=f"Deleted card {name}")
    return JsonResponse({"ok": True})


@login_required
@require_POST
def api_apps_reorder(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    order = body.get("order")
    if not isinstance(order, list) or not order:
        return JsonResponse({"error": "order required"}, status=400)
    ids = []
    for raw in order:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            return JsonResponse({"error": "invalid id"}, status=400)
    services_qs = Service.objects.filter(
        pk__in=ids,
        enabled=True,
        is_misc=False,
        widget_type=Service.WidgetType.NONE,
    )
    if services_qs.count() != len(set(ids)):
        return JsonResponse({"error": "invalid apps order"}, status=400)
    for index, service_id in enumerate(ids):
        Service.objects.filter(pk=service_id).update(sort_order=index)
    log_audit("admin", request=request, user=request.user, message="Reordered Apps cards")
    return JsonResponse({"ok": True})


@login_required
@require_GET
def api_system(request):
    return JsonResponse(services.get_system_stats())


@login_required
@require_POST
def api_system_reboot(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    ok, message = hostops.schedule_reboot()
    if not ok:
        return JsonResponse({"error": message}, status=409)
    log_audit(
        "admin",
        request=request,
        user=request.user,
        message="Requested host reboot",
    )
    return JsonResponse({"ok": True, "message": message})


@login_required
@require_GET
def api_system_usb(request):
    return JsonResponse(hostops.get_cached_usb())


@login_required
@require_POST
def api_system_usb_unmount(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        body = {}
    ok, message = hostops.unmount_path(body.get("path") or "")
    if not ok:
        return JsonResponse({"error": message}, status=400)
    log_audit(
        "admin",
        request=request,
        user=request.user,
        message=f"Unmounted USB path {body.get('path')}",
    )
    return JsonResponse({"ok": True, "message": message})


@login_required
@require_GET
def api_docker(request):
    return JsonResponse(services.get_docker_containers())


@login_required
@require_POST
def api_docker_restart(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        body = {}
    name = (body.get("name") or "").strip()
    ok, message = hostops.restart_container(name)
    if not ok:
        status = 400 if "Invalid" in message or "not found" in message.lower() else 502
        return JsonResponse({"error": message}, status=status)
    log_audit(
        "admin",
        request=request,
        user=request.user,
        message=f"Restarted container {name}",
    )
    return JsonResponse({"ok": True, "message": message})


@login_required
@require_GET
def api_health(request):
    return JsonResponse({"services": services.get_cached_health()})


@login_required
@require_GET
def api_alerts(request):
    return JsonResponse({"alerts": services.get_cached_alerts(limit=30)})


@login_required
@require_POST
def api_alerts_ack(request):
    from core.access import can_ack_alerts

    if not can_ack_alerts(request.user):
        return JsonResponse({"error": "Forbidden"}, status=403)
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
    from core.access import visible_service_ids

    payload = dict(services.get_cached_uptime_payload())
    payload["kuma_can_install"] = request.user.is_superuser
    allowed = visible_service_ids(request.user)
    uptime = payload.get("uptime") or {}
    payload["uptime"] = {key: value for key, value in uptime.items() if int(key) in allowed}
    return JsonResponse(payload)


@login_not_required
@require_GET
def api_widgets(request):
    from core.access import visible_service_ids

    allowed = visible_service_ids(request.user if request.user.is_authenticated else None)
    return JsonResponse({"widgets": services.fetch_all_widgets(service_ids=allowed)})


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
    return JsonResponse(services.fetch_weather())


@login_required
@require_GET
def api_service_files(request, service_id):
    from . import explore

    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    service = get_object_or_404(Service, pk=service_id, enabled=True)
    try:
        payload = explore.list_service_files(service, request.GET.get("path") or "")
    except explore.ExploreError as exc:
        return JsonResponse({"error": exc.message}, status=exc.status)
    return JsonResponse(payload)


@login_required
@require_GET
def api_service_file_content(request, service_id):
    from . import explore

    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    service = get_object_or_404(Service, pk=service_id, enabled=True)
    try:
        result = explore.read_service_file(service, request.GET.get("path") or "")
    except explore.ExploreError as exc:
        return JsonResponse({"error": exc.message}, status=exc.status)
    if result["kind"] == "image":
        response = HttpResponse(result["body"], content_type=result["content_type"])
        safe_name = result["name"].replace('"', "").replace("\\", "").replace("\n", "").replace("\r", "")
        response["Content-Disposition"] = f'inline; filename="{safe_name}"'
        return response
    return JsonResponse(
        {
            "kind": "text",
            "name": result["name"],
            "text": result["body"].decode("utf-8", errors="replace"),
        }
    )


def _troubleshoot_service(request, service_id):
    from core.access import can_open_service

    service = get_object_or_404(Service, pk=service_id, enabled=True)
    if not can_open_service(request.user, service):
        return None
    return service


@login_required
@require_POST
def api_service_troubleshoot_start(request, service_id):
    from dashboard.debug import incident_payload, start_diagnosis

    service = _troubleshoot_service(request, service_id)
    if service is None:
        return JsonResponse({"error": "Not found"}, status=404)
    incident, error = start_diagnosis(service, request.user)
    if error:
        status = 429 if "Too many" in error or "busy" in error else 400
        return JsonResponse({"error": error}, status=status)
    payload = incident_payload(incident, is_superuser=request.user.is_superuser)
    payload["status"] = incident.status
    return JsonResponse(payload, status=202)


@login_required
@require_GET
def api_service_troubleshoot_poll(request, service_id, incident_id):
    from dashboard.debug import incident_payload

    service = _troubleshoot_service(request, service_id)
    if service is None:
        return JsonResponse({"error": "Not found"}, status=404)
    incident = get_object_or_404(DebugIncident, incident_id=incident_id, service=service)
    return JsonResponse(incident_payload(incident, is_superuser=request.user.is_superuser))


@login_required
@require_POST
def api_service_troubleshoot_repair(request, service_id, incident_id):
    from dashboard.debug_actions import start_repair

    service = _troubleshoot_service(request, service_id)
    if service is None:
        return JsonResponse({"error": "Not found"}, status=404)
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        body = {}
    action_id = (body.get("action_id") or "").strip()
    if action_id != "ACTION_RECHECK" and not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    incident = get_object_or_404(DebugIncident, incident_id=incident_id, service=service)
    confirmed = bool(body.get("confirmed") or body.get("confirm_token"))
    payload, error, status = start_repair(incident, action_id, request.user, confirmed=confirmed)
    if error:
        hint = "Check again" if error == "stale_diagnosis" else ""
        data = {"error": error}
        if hint:
            data["hint"] = hint
        return JsonResponse(data, status=status)
    return JsonResponse(payload, status=status)


@login_required
@require_GET
def api_service_troubleshoot_repair_poll(request, service_id, incident_id, job_id):
    service = _troubleshoot_service(request, service_id)
    if service is None:
        return JsonResponse({"error": "Not found"}, status=404)
    incident = get_object_or_404(DebugIncident, incident_id=incident_id, service=service)
    job = (incident.repair_jobs or {}).get(job_id)
    if not job:
        return JsonResponse({"error": "Not found"}, status=404)
    return JsonResponse({"job_id": job_id, **job})


@login_required
@require_POST
def api_service_troubleshoot_cancel(request, service_id, incident_id):
    service = _troubleshoot_service(request, service_id)
    if service is None:
        return JsonResponse({"error": "Not found"}, status=404)
    incident = get_object_or_404(DebugIncident, incident_id=incident_id, service=service)
    if incident.status in (
        DebugIncident.Status.QUEUED,
        DebugIncident.Status.RUNNING,
    ):
        incident.cancel_requested = True
        incident.save(update_fields=["cancel_requested"])
        return JsonResponse({"ok": True, "status": "cancelling"})
    return JsonResponse({"error": "This run cannot be cancelled."}, status=409)


@login_required
@require_GET
def api_service_troubleshoot_report_txt(request, service_id, incident_id):
    service = _troubleshoot_service(request, service_id)
    if service is None:
        return JsonResponse({"error": "Not found"}, status=404)
    incident = get_object_or_404(DebugIncident, incident_id=incident_id, service=service)
    body = incident.report_text or "No report yet."
    response = HttpResponse(body, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{incident.incident_id}.txt"'
    return response


@login_required
@require_GET
def api_service_troubleshoot_report_json(request, service_id, incident_id):
    from dashboard.debug import incident_payload

    service = _troubleshoot_service(request, service_id)
    if service is None:
        return JsonResponse({"error": "Not found"}, status=404)
    incident = get_object_or_404(DebugIncident, incident_id=incident_id, service=service)
    payload = incident_payload(incident, is_superuser=request.user.is_superuser)
    payload["report_text"] = incident.report_text
    return JsonResponse(payload)
