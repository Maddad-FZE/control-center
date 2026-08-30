import json
from html.parser import HTMLParser

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.html import escape
from django.views.decorators.http import require_GET, require_POST

from core.models import log_audit
from core.version import get_current_version
from dashboard.models import Service

from .addons import addon_states_for_catalog, get_addon_by_slug, is_addon_enabled, set_addon_enabled
from .catalog import build_catalog_items, all_categories
from .icons import default_icon_url
from . import cloudflare as cf
from .installer import detect_services_host, start_install, status_payload, uninstall
from .models import CatalogRelease, InstalledService, LibraryNote, TunnelRoute

_ALLOWED_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "ul",
    "ol",
    "li",
    "p",
    "br",
    "div",
    "span",
    "h3",
    "h4",
}


class _NoteSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._out = []

    def handle_starttag(self, tag, attrs):
        if tag not in _ALLOWED_TAGS:
            return
        self._out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag not in _ALLOWED_TAGS:
            return
        self._out.append(f"</{tag}>")

    def handle_data(self, data):
        self._out.append(escape(data))

    def result(self):
        return "".join(self._out)


def sanitize_note_html(raw):
    parser = _NoteSanitizer()
    parser.feed(raw or "")
    parser.close()
    return parser.result()[:20000]


@login_required
def library_view(request):
    if not request.user.is_superuser:
        return redirect("dashboard")

    host = detect_services_host(request)

    addon_states = addon_states_for_catalog()
    installed_map = {row.slug: row for row in InstalledService.objects.all()}
    release_map = {
        row.repo: row.latest_version
        for row in CatalogRelease.objects.all()
    }
    service_cards = {
        row.catalog_slug: row.id
        for row in Service.objects.exclude(catalog_slug="")
    }
    catalog_items = build_catalog_items(
        addon_states,
        installed_map,
        release_map,
        app_version=get_current_version(),
        service_cards=service_cards,
    )
    tunnel = cf.status_payload()
    published_by_slug = {
        row.catalog_slug: row.hostname
        for row in TunnelRoute.objects.exclude(catalog_slug="")
    }
    for item in catalog_items:
        port = item.get("host_port") or 0
        if item.get("type") == "service" and port:
            item["open_href"] = f"http://{host}:{port}/"
        item["can_publish"] = (
            item.get("type") == "service"
            and item.get("slug") != "cloudflare-tunnel"
            and item.get("installed")
            and bool(port)
            and tunnel.get("linked")
        )
        item["published_hostname"] = published_by_slug.get(item.get("slug"), "")
        item["is_tunnel"] = item.get("slug") == "cloudflare-tunnel"

    return render(
        request,
        "library/index.html",
        {
            "catalog_items": catalog_items,
            "categories": all_categories(),
            "default_app_icon": default_icon_url(),
            "library_note": LibraryNote.load(),
            "tunnel_status": tunnel,
        },
    )


@login_required
@require_POST
def api_addon_toggle(request, slug):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    if not get_addon_by_slug(slug):
        return JsonResponse({"error": "Unknown addon"}, status=404)

    new_state = not is_addon_enabled(slug)
    set_addon_enabled(slug, new_state)
    log_audit(
        "admin",
        request=request,
        user=request.user,
        message=f"Addon {slug} {'enabled' if new_state else 'disabled'}",
    )
    return JsonResponse({"ok": True, "slug": slug, "enabled": new_state})


@login_required
@require_POST
def api_service_install(request, slug):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    started, message = start_install(slug, request=request)
    if not started:
        return JsonResponse({"error": message}, status=409)
    log_audit(
        "admin",
        request=request,
        user=request.user,
        message=f"Started install of {slug}",
    )
    return JsonResponse({"ok": True, "message": message, **status_payload(slug)})


@login_required
@require_POST
def api_service_uninstall(request, slug):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    remove_data = request.POST.get("remove_data") in ("1", "true", "yes", "on")
    ok, message = uninstall(slug, remove_data=remove_data)
    if not ok:
        return JsonResponse({"error": message}, status=500)
    log_audit(
        "admin",
        request=request,
        user=request.user,
        message=f"Uninstalled {slug}" + (" with data" if remove_data else ""),
    )
    return JsonResponse({"ok": True, "message": message})


@login_required
@require_GET
def api_service_status(request, slug):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(status_payload(slug))


@login_required
@require_POST
def api_library_notes(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    note = LibraryNote.load()
    note.body = sanitize_note_html(payload.get("body") or "")
    note.save()
    return JsonResponse({"ok": True, "body": note.body})


def _json_body(request):
    try:
        return json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return None


@login_required
@require_GET
def api_tunnel_status(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse(cf.status_payload())


@login_required
@require_POST
def api_tunnel_link(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    try:
        result = cf.link_account(
            body.get("token") or "",
            account_id=body.get("account_id") or "",
            zone_id=body.get("zone_id") or "",
            confirm=bool(body.get("confirm")),
        )
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"error": str(exc)[:200]}, status=502)
    if result.get("ok"):
        log_audit("admin", request=request, user=request.user, message="Linked Cloudflare tunnel")
    return JsonResponse(result)


@login_required
@require_POST
def api_tunnel_unlink(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    body = _json_body(request) or {}
    cf.unlink_account(delete_remote=bool(body.get("delete_remote")))
    log_audit("admin", request=request, user=request.user, message="Unlinked Cloudflare tunnel")
    return JsonResponse({"ok": True, **cf.status_payload()})


@login_required
@require_POST
def api_tunnel_publish(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    hostname = (body.get("hostname") or "").strip()
    subdomain = (body.get("subdomain") or "").strip()
    catalog_slug = (body.get("slug") or "").strip()
    service_id = body.get("service_id")
    service = None
    if service_id:
        service = Service.objects.filter(pk=service_id).first()
        if not service:
            return JsonResponse({"error": "Unknown card."}, status=404)
        catalog_slug = catalog_slug or service.catalog_slug
    origin = cf.origin_for_service(
        service=service,
        catalog_slug=catalog_slug,
        host_port=body.get("host_port") or 0,
    )
    try:
        route = cf.publish_route(
            hostname,
            origin,
            catalog_slug=catalog_slug,
            service_id=service.id if service else service_id,
            request=request,
            subdomain=subdomain,
        )
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"error": str(exc)[:200]}, status=502)
    log_audit(
        "admin",
        request=request,
        user=request.user,
        message=f"Published {route.hostname} → {route.origin_url}",
    )
    return JsonResponse({"ok": True, "hostname": route.hostname, "origin_url": route.origin_url})


@login_required
@require_POST
def api_tunnel_unpublish(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    try:
        cf.unpublish_route(body.get("hostname") or "")
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"error": str(exc)[:200]}, status=502)
    log_audit(
        "admin",
        request=request,
        user=request.user,
        message=f"Unpublished {body.get('hostname')}",
    )
    return JsonResponse({"ok": True})
