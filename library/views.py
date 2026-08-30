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
from .installer import detect_services_host, start_install, status_payload, uninstall
from .models import CatalogRelease, InstalledService, LibraryNote

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
    for item in catalog_items:
        port = item.get("host_port") or 0
        if item.get("type") == "service" and port:
            item["open_href"] = f"http://{host}:{port}/"

    return render(
        request,
        "library/index.html",
        {
            "catalog_items": catalog_items,
            "categories": all_categories(),
            "default_app_icon": default_icon_url(),
            "library_note": LibraryNote.load(),
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
