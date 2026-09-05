import json
import time

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_not_required, login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET, require_POST

from . import updates
from .forms import AppearanceForm, ProfileForm, SetupAdminForm, SiteSettingsForm
from .models import AuditEvent, SettingsNote, UpdateStatus, log_audit
from .notes import sanitize_note_html
from .site_settings import clear_site_settings_cache, get_site_settings, update_weather_coordinates
from .totp import twofa_enabled
from .version import get_current_version, get_git_revision


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


@method_decorator(login_not_required, name="dispatch")
class ThemedLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        from core.totp import twofa_enabled

        user = form.get_user()
        if twofa_enabled(user):
            self.request.session["pending_2fa_user_id"] = user.id
            self.request.session["pending_2fa_backend"] = getattr(user, "backend", "")
            self.request.session["pending_2fa_at"] = time.time()
            return redirect("login_2fa")
        return super().form_valid(form)


class ThemedLogoutView(LogoutView):
    next_page = "login"


class ThemedPasswordChangeView(PasswordChangeView):
    def get(self, request, *args, **kwargs):
        return redirect(reverse("profile") + "?section=security")

    def post(self, request, *args, **kwargs):
        return redirect(reverse("profile") + "?section=security")


@login_not_required
def setup_view(request):
    if User.objects.exists():
        return redirect("dashboard")
    form = SetupAdminForm()
    if request.method == "POST":
        form = SetupAdminForm(request.POST)
        if form.is_valid():
            try:
                user = User.objects.create_superuser(
                    username=form.cleaned_data["username"],
                    email="",
                    password=form.cleaned_data["password1"],
                )
            except ValidationError as exc:
                for message in exc.messages:
                    form.add_error("password1", message)
            else:
                login(request, user)
                messages.success(request, "Admin account created. Welcome!")
                return redirect("dashboard")
    return render(request, "core/setup.html", {"form": form})


@login_required
def audit_log_view(request):
    if not request.user.is_superuser:
        return redirect("dashboard")
    return redirect(reverse("settings") + "?section=audit")


def _audit_settings_context(request):
    event_type = request.GET.get("event_type", "").strip()
    search = request.GET.get("q", "").strip()
    qs = AuditEvent.objects.all()
    if event_type:
        qs = qs.filter(event_type=event_type)
    if search:
        qs = qs.filter(
            Q(username__icontains=search)
            | Q(message__icontains=search)
            | Q(ip_address__icontains=search)
        )
    paginator = Paginator(qs, 50)
    page_number = request.GET.get("page", "1")
    page_obj = paginator.get_page(page_number)
    return {
        "audit_events": page_obj,
        "audit_event_types": AuditEvent.EventType.choices,
        "audit_event_type": event_type,
        "audit_search": search,
    }


PROFILE_SECTIONS = {"account", "security", "vault"}


def _profile_section(value):
    if not isinstance(value, str):
        value = ""
    return value if value in PROFILE_SECTIONS else "account"


@login_required
def profile_view(request):
    if "tab" in request.GET and "section" not in request.GET:
        params = request.GET.copy()
        tab = params.get("tab", "account")
        del params["tab"]
        params["section"] = _profile_section(tab)
        return redirect(f"{reverse('profile')}?{params.urlencode()}")

    active_section = _profile_section(request.GET.get("section", "account"))
    profile = getattr(request.user, "profile", None)
    must_change = bool(profile and profile.must_change_password)
    if must_change and request.method == "GET" and active_section != "security":
        return redirect(reverse("profile") + "?section=security")

    profile_form = ProfileForm(instance=request.user)
    password_form = PasswordChangeForm(user=request.user)

    if request.method == "POST":
        form_type = request.POST.get("form")
        active_section = _profile_section(request.POST.get("section", active_section))
        if form_type == "profile":
            profile_form = ProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile updated.")
                return redirect(reverse("profile") + "?section=account")
        elif form_type == "password":
            password_form = PasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, request.user)
                if profile and profile.must_change_password:
                    profile.must_change_password = False
                    profile.save(update_fields=["must_change_password"])
                messages.success(request, "Password updated.")
                return redirect(reverse("profile") + "?section=security")
            active_section = "security"

    return render(
        request,
        "core/profile.html",
        {
            "profile_form": profile_form,
            "password_form": password_form,
            "user_obj": request.user,
            "twofa_enabled": twofa_enabled(request.user),
            "active_section": active_section,
            "must_change_password": must_change,
        },
    )


@login_required
def settings_view(request):
    if not request.user.is_superuser:
        messages.info(request, "Settings are available to admins only.")
        return redirect("profile")

    profile = request.user.profile
    site_settings = get_site_settings()
    appearance_form = AppearanceForm(instance=profile)
    site_form = SiteSettingsForm(instance=site_settings)
    users = User.objects.order_by("username").select_related("profile")
    active_section = request.GET.get("section", "appearance")

    if request.method == "POST":
        form_type = request.POST.get("form")
        active_section = request.POST.get("section", active_section)
        if form_type == "appearance":
            appearance_form = AppearanceForm(request.POST, instance=profile)
            if appearance_form.is_valid():
                appearance_form.save()
                messages.success(request, "Appearance saved.")
                return redirect(reverse("settings") + "?section=appearance")
        elif form_type == "site":
            site_form = SiteSettingsForm(
                request.POST, request.FILES, instance=site_settings
            )
            if site_form.is_valid():
                site_obj = site_form.save(commit=False)
                update_weather_coordinates(site_obj)
                site_obj.save()
                clear_site_settings_cache()
                messages.success(request, "Site settings saved.")
                return redirect(reverse("settings") + "?section=site")

    platform = {
        "site_title": (site_settings.title or "").strip() or django_settings.SITE_TITLE,
        "health_check_enabled": django_settings.HEALTH_CHECK_ENABLED,
        "debug": django_settings.DEBUG,
        "ntfy_configured": bool(django_settings.NTFY_URL and django_settings.NTFY_TOPIC),
        "version": get_current_version(),
        "revision": get_git_revision(),
    }

    update_status = updates.clear_stale_install_progress(UpdateStatus.load())

    context = {
        "appearance_form": appearance_form,
        "site_form": site_form,
        "site_settings": site_settings,
        "users": users,
        "platform": platform,
        "active_section": active_section,
        "update_status": update_status,
        "update_ready": updates.update_available(update_status),
        "current_version": get_current_version(),
        "github_repo": django_settings.GITHUB_REPO,
        "install_allowed": django_settings.UPDATES_ALLOW_INSTALL,
        "check_interval_hours": django_settings.UPDATE_CHECK_INTERVAL_HOURS,
        "settings_note": SettingsNote.load(),
        "console_enabled": django_settings.CONSOLE_ENABLED,
        "console_host_enabled": django_settings.CONSOLE_HOST_ENABLED,
        "twofa_enabled": twofa_enabled(request.user),
    }
    context.update(_audit_settings_context(request))
    try:
        from library.cloudflare import status_payload as tunnel_status

        context["tunnel_status"] = tunnel_status()
    except Exception:
        context["tunnel_status"] = {"installed": False, "linked": False, "routes": [], "token_url": ""}

    return render(request, "core/settings.html", context)


@login_required
@require_POST
def api_settings_notes(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    note = SettingsNote.load()
    note.body = sanitize_note_html(payload.get("body") or "")
    note.save()
    return JsonResponse({"ok": True, "body": note.body})


@login_required
@require_GET
def api_update_status(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    status = UpdateStatus.load()
    return JsonResponse(updates.status_payload(status))


@login_required
@require_POST
def api_update_check(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    status = updates.maybe_check_for_update(force=True)
    log_audit(
        "admin",
        request=request,
        user=request.user,
        message="Checked for updates",
    )
    return JsonResponse(updates.status_payload(status))


@login_required
@require_POST
def api_update_install(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    status = UpdateStatus.load()
    if not updates.update_available(status):
        return JsonResponse({"error": "Already up to date."}, status=400)
    started, message = updates.start_install(
        status.latest_version, username=request.user.username
    )
    if not started:
        return JsonResponse({"error": message}, status=409)
    log_audit(
        "admin",
        request=request,
        user=request.user,
        message=f"Started update to {status.latest_version}",
    )
    payload = updates.status_payload()
    payload["message"] = message
    return JsonResponse(payload)


@login_not_required
@require_GET
def service_worker_view(request):
    from .version import get_asset_token

    sw_path = django_settings.BASE_DIR / "static" / "js" / "sw.js"
    body = sw_path.read_text(encoding="utf-8").replace("__ASSET_VERSION__", get_asset_token())
    response = HttpResponse(body, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@login_not_required
@require_GET
def public_media_view(request, path):
    from django.views.static import serve

    return serve(request, path, document_root=django_settings.MEDIA_ROOT)


@login_required
@require_GET
def api_logs_sources(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    from core.logs import list_sources

    return JsonResponse({"sources": list_sources()})


@login_required
@require_GET
def api_logs(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    from core.logs import fetch_logs

    source = request.GET.get("source", "app")
    query = request.GET.get("q", "")
    tail = request.GET.get("tail", "400")
    since = request.GET.get("since") or None
    payload = fetch_logs(source, query=query, tail=tail, since=since)
    if payload.get("error") and not payload.get("lines"):
        return JsonResponse(payload, status=400)
    return JsonResponse(payload)


@login_required
@require_GET
def api_logs_download(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    from core.logs import download_logs

    source = request.GET.get("source", "app")
    body, error = download_logs(source)
    if error:
        return JsonResponse({"error": error}, status=400)
    response = HttpResponse(body, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{source.replace(":", "-")}.log"'
    return response


@login_required
@require_POST
def api_console_ticket(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    if not django_settings.CONSOLE_ENABLED:
        return JsonResponse({"error": "Console is disabled."}, status=403)
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    from core.console import create_ticket

    token, error = create_ticket(
        request.user,
        (payload.get("target") or "app").strip(),
        _client_ip(request),
        payload.get("password") or "",
        totp_code=payload.get("totp") or payload.get("code") or "",
        vault_entry_id=payload.get("vault_entry_id"),
    )
    if error:
        return JsonResponse({"error": error}, status=403)
    return JsonResponse({"ticket": token})


TWOFA_PENDING_TTL = 300
TWOFA_FAIL_LIMIT = 5


@login_not_required
def login_2fa_view(request):
    user_id = request.session.get("pending_2fa_user_id")
    started = request.session.get("pending_2fa_at") or 0
    if not user_id or time.time() - float(started) > TWOFA_PENDING_TTL:
        request.session.pop("pending_2fa_user_id", None)
        messages.error(request, "Sign-in expired. Enter your password again.")
        return redirect("login")
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if not user:
        return redirect("login")
    error = ""
    if request.method == "POST":
        fail_key = f"2fa:fail:{user.id}"
        fails = int(cache.get(fail_key) or 0)
        if fails >= TWOFA_FAIL_LIMIT:
            error = "Too many attempts. Wait a few minutes."
        else:
            from core.totp import consume_recovery_code, verify_totp, twofa_enabled
            from core.models import log_audit

            code = (request.POST.get("code") or "").strip()
            ok = False
            used_recovery = False
            if twofa_enabled(user) and verify_totp(user.profile.totp_secret, code):
                ok = True
            elif consume_recovery_code(user, code):
                ok = True
                used_recovery = True
            if ok:
                cache.delete(fail_key)
                backend = request.session.pop("pending_2fa_backend", "") or "django.contrib.auth.backends.ModelBackend"
                request.session.pop("pending_2fa_user_id", None)
                request.session.pop("pending_2fa_at", None)
                login(request, user, backend=backend)
                log_audit(
                    "2fa",
                    request=request,
                    user=user,
                    message="Recovery code used" if used_recovery else "Signed in with 2FA",
                )
                return redirect(django_settings.LOGIN_REDIRECT_URL)
            cache.set(fail_key, fails + 1, 600)
            log_audit("2fa", request=request, user=user, message="Failed 2FA challenge")
            error = "Invalid authenticator or recovery code."
    return render(request, "registration/login_2fa.html", {"error": error})


def _json_body(request):
    try:
        return json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return None


def _require_admin(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    return None


@login_required
def api_users(request):
    forbidden = _require_admin(request)
    if forbidden:
        return forbidden
    from core import users as users_api

    if request.method == "GET":
        return JsonResponse({"users": users_api.list_users(request.user)})
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    try:
        row = users_api.create_user(request.user, payload, request=request)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    return JsonResponse(row, status=201)


@login_required
@require_GET
def api_users_services(request):
    forbidden = _require_admin(request)
    if forbidden:
        return forbidden
    from core import users as users_api

    return JsonResponse({"services": users_api.enabled_services()})


@login_required
def api_user_detail(request, user_id):
    forbidden = _require_admin(request)
    if forbidden:
        return forbidden
    from core import users as users_api

    user = get_object_or_404(User, pk=user_id)
    if request.method == "GET":
        return JsonResponse(users_api.serialize_user(user, request.user))
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if request.method in ("PATCH", "PUT"):
        try:
            row = users_api.update_user(request.user, user, payload, request=request)
        except ValidationError as exc:
            return JsonResponse({"error": " ".join(exc.messages)}, status=400)
        return JsonResponse(row)
    if request.method == "DELETE":
        try:
            users_api.delete_user(request.user, user, payload.get("username", ""), request=request)
        except ValidationError as exc:
            return JsonResponse({"error": " ".join(exc.messages)}, status=400)
        return JsonResponse({"ok": True})
    return JsonResponse({"error": "Method not allowed"}, status=405)


@login_required
@require_POST
def api_user_password(request, user_id):
    forbidden = _require_admin(request)
    if forbidden:
        return forbidden
    from core import users as users_api

    user = get_object_or_404(User, pk=user_id)
    payload = _json_body(request) or {}
    try:
        row = users_api.set_password(
            request.user,
            user,
            payload.get("password") or "",
            request=request,
            generate=bool(payload.get("generate")),
        )
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    return JsonResponse(row)


@login_required
@require_POST
def api_user_2fa_reset(request, user_id):
    forbidden = _require_admin(request)
    if forbidden:
        return forbidden
    from core import users as users_api

    user = get_object_or_404(User, pk=user_id)
    return JsonResponse(users_api.reset_twofa(request.user, user, request=request))


@login_required
@require_POST
def api_2fa_start(request):
    from django.utils import timezone
    from core.models import log_audit
    from core.totp import generate_secret, provisioning_uri, qr_data_uri, twofa_enabled

    if twofa_enabled(request.user):
        return JsonResponse({"error": "2FA is already enabled."}, status=400)
    secret = generate_secret()
    request.session["pending_totp_secret"] = secret
    issuer = get_site_settings().title or django_settings.SITE_TITLE
    uri = provisioning_uri(request.user.username, secret, issuer=issuer or "Control Center")
    log_audit("2fa", request=request, user=request.user, message="Started 2FA enrolment")
    return JsonResponse({"secret": secret, "uri": uri, "qr": qr_data_uri(uri)})


@login_required
@require_POST
def api_2fa_confirm(request):
    from django.utils import timezone
    from core.models import log_audit
    from core.totp import generate_recovery_codes, store_recovery_codes, verify_totp

    payload = _json_body(request) or {}
    secret = request.session.get("pending_totp_secret") or ""
    if not secret:
        return JsonResponse({"error": "Start 2FA setup first."}, status=400)
    if not verify_totp(secret, payload.get("code") or ""):
        return JsonResponse({"error": "Invalid authenticator code."}, status=400)
    profile = request.user.profile
    profile.totp_secret = secret
    profile.totp_confirmed_at = timezone.now()
    profile.save(update_fields=["totp_secret", "totp_confirmed_at"])
    request.session.pop("pending_totp_secret", None)
    codes = generate_recovery_codes()
    store_recovery_codes(request.user, codes)
    log_audit("2fa", request=request, user=request.user, message="Enabled 2FA")
    return JsonResponse({"ok": True, "recovery_codes": codes})


@login_required
@require_POST
def api_2fa_disable(request):
    from core.models import log_audit
    from core.totp import clear_twofa, consume_recovery_code, twofa_enabled, verify_totp

    payload = _json_body(request) or {}
    if not request.user.check_password(payload.get("password") or ""):
        return JsonResponse({"error": "Invalid password."}, status=403)
    if twofa_enabled(request.user):
        code = payload.get("code") or ""
        if not verify_totp(request.user.profile.totp_secret, code) and not consume_recovery_code(
            request.user, code
        ):
            return JsonResponse({"error": "Invalid authenticator or recovery code."}, status=400)
    clear_twofa(request.user)
    log_audit("2fa", request=request, user=request.user, message="Disabled 2FA")
    return JsonResponse({"ok": True})


@login_required
@require_GET
def api_vault_services(request):
    from core.access import visible_services_for

    rows = list(visible_services_for(request.user).order_by("name").values("id", "name"))
    return JsonResponse({"services": rows})


@login_required
def api_vault_entries(request):
    from core import vault as vault_api
    from core.models import VaultEntry, log_audit
    from dashboard.models import Service

    if request.method == "GET":
        rows = [vault_api.serialize_entry(e) for e in vault_api.list_entries(request.user)]
        return JsonResponse({"entries": rows})
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    label = (payload.get("label") or "").strip()
    service = None
    service_id = payload.get("service_id")
    if service_id:
        service = Service.objects.filter(pk=service_id).first()
        if not service:
            return JsonResponse({"error": "Unknown service."}, status=400)
        if not label:
            label = service.name
    if not label:
        return JsonResponse({"error": "Label is required."}, status=400)
    entry = VaultEntry(
        user=request.user,
        service=service,
        label=label,
        username=(payload.get("username") or "").strip(),
        secret_ciphertext=payload.get("secret") or "",
        kind=payload.get("kind") or VaultEntry.Kind.PASSWORD,
        notes=(payload.get("notes") or "").strip(),
    )
    try:
        entry.save()
    except Exception:
        return JsonResponse({"error": "Could not save entry (duplicate label?)."}, status=400)
    log_audit("vault", request=request, user=request.user, message=f"Added vault entry {entry.label}")
    return JsonResponse(vault_api.serialize_entry(entry), status=201)


@login_required
def api_vault_entry(request, entry_id):
    from core import vault as vault_api
    from core.models import VaultEntry, log_audit

    entry = get_object_or_404(VaultEntry, pk=entry_id, user=request.user)
    if request.method == "GET":
        return JsonResponse(vault_api.serialize_entry(entry))
    payload = _json_body(request) if request.body else {}
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if request.method in ("PATCH", "PUT"):
        from dashboard.models import Service

        if "label" in payload:
            entry.label = (payload.get("label") or entry.label).strip()
        if "username" in payload:
            entry.username = (payload.get("username") or "").strip()
        if "secret" in payload and payload.get("secret"):
            entry.secret_ciphertext = payload.get("secret")
        if "kind" in payload:
            entry.kind = payload.get("kind") or entry.kind
        if "notes" in payload:
            entry.notes = (payload.get("notes") or "").strip()
        if "service_id" in payload:
            sid = payload.get("service_id")
            entry.service = Service.objects.filter(pk=sid).first() if sid else None
        entry.save()
        log_audit("vault", request=request, user=request.user, message=f"Updated vault entry {entry.label}")
        return JsonResponse(vault_api.serialize_entry(entry))
    if request.method == "DELETE":
        label = entry.label
        entry.delete()
        log_audit("vault", request=request, user=request.user, message=f"Deleted vault entry {label}")
        return JsonResponse({"ok": True})
    return JsonResponse({"error": "Method not allowed"}, status=405)


@login_required
@require_POST
def api_vault_reveal(request, entry_id):
    from core import vault as vault_api
    from core.models import VaultEntry

    entry = get_object_or_404(VaultEntry, pk=entry_id, user=request.user)
    payload = _json_body(request) or {}
    if not vault_api.step_up_ok(request.user):
        error = vault_api.require_step_up(
            request.user, payload.get("password") or "", _client_ip(request)
        )
        if error:
            return JsonResponse({"error": error}, status=403)
    vault_api.audit_reveal(request, request.user, entry)
    return JsonResponse(vault_api.serialize_entry(entry, include_secret=True))
