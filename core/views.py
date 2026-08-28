from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required, login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET, require_POST

from . import updates
from .forms import AppearanceForm, ProfileForm, SetupAdminForm, SiteSettingsForm
from .models import AuditEvent, UpdateStatus, log_audit
from .site_settings import clear_site_settings_cache, get_site_settings, update_weather_coordinates
from .version import get_current_version, get_git_revision


@method_decorator(login_not_required, name="dispatch")
class ThemedLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


class ThemedLogoutView(LogoutView):
    next_page = "login"


class ThemedPasswordChangeView(PasswordChangeView):
    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("profile")


@login_not_required
def setup_view(request):
    if User.objects.exists():
        return redirect("dashboard")
    form = SetupAdminForm()
    if request.method == "POST":
        form = SetupAdminForm(request.POST)
        if form.is_valid():
            user = User.objects.create_superuser(
                username=form.cleaned_data["username"],
                email="",
                password=form.cleaned_data["password1"],
            )
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


@login_required
def profile_view(request):
    profile_form = ProfileForm(instance=request.user)
    if request.method == "POST" and request.POST.get("form") == "profile":
        profile_form = ProfileForm(request.POST, instance=request.user)
        if profile_form.is_valid():
            profile_form.save()
            messages.success(request, "Profile updated.")
            return redirect("profile")
    return render(
        request,
        "core/profile.html",
        {
            "profile_form": profile_form,
            "user_obj": request.user,
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
        "site_title": django_settings.SITE_TITLE,
        "health_check_enabled": django_settings.HEALTH_CHECK_ENABLED,
        "debug": django_settings.DEBUG,
        "ntfy_configured": bool(django_settings.NTFY_URL and django_settings.NTFY_TOPIC),
        "version": get_current_version(),
        "revision": get_git_revision(),
    }

    update_status = UpdateStatus.load()

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
    }
    context.update(_audit_settings_context(request))

    return render(request, "core/settings.html", context)


@login_required
@require_GET
def api_update_status(request):
    if not request.user.is_superuser:
        return JsonResponse({"error": "Forbidden"}, status=403)
    status = updates.maybe_check_for_update()
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
    sw_path = django_settings.BASE_DIR / "static" / "js" / "sw.js"
    response = FileResponse(sw_path.open("rb"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response
