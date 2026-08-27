from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST

from .forms import ProfileForm, SettingsForm, SiteSettingsForm
from .models import AuditEvent
from .site_settings import clear_site_settings_cache, get_site_settings, update_weather_coordinates


@method_decorator(login_not_required, name="dispatch")
class ThemedLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


class ThemedLogoutView(LogoutView):
    next_page = "login"


class ThemedPasswordChangeView(PasswordChangeView):
    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("profile")


@login_required
def audit_log_view(request):
    events = AuditEvent.objects.all()[:200]
    return render(request, "core/audit_log.html", {"events": events})


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
    profile = request.user.profile
    settings_form = SettingsForm(instance=profile)
    site_settings = get_site_settings()
    site_form = None
    users = None
    if request.user.is_superuser:
        users = User.objects.order_by("username").select_related("profile")
        site_form = SiteSettingsForm(instance=site_settings)

    if request.method == "POST":
        form_type = request.POST.get("form")
        if form_type == "settings":
            settings_form = SettingsForm(request.POST, instance=profile)
            if settings_form.is_valid():
                settings_form.save()
                messages.success(request, "Settings saved.")
                return redirect("settings")
        elif form_type == "site" and request.user.is_superuser:
            site_form = SiteSettingsForm(
                request.POST, request.FILES, instance=site_settings
            )
            if site_form.is_valid():
                site_obj = site_form.save(commit=False)
                update_weather_coordinates(site_obj)
                site_obj.save()
                clear_site_settings_cache()
                messages.success(request, "Site settings saved.")
                return redirect("settings")

    platform = {
        "site_title": django_settings.SITE_TITLE,
        "health_check_enabled": django_settings.HEALTH_CHECK_ENABLED,
        "debug": django_settings.DEBUG,
        "ntfy_configured": bool(django_settings.NTFY_URL and django_settings.NTFY_TOPIC),
    }

    return render(
        request,
        "core/settings.html",
        {
            "settings_form": settings_form,
            "site_form": site_form,
            "site_settings": site_settings,
            "users": users,
            "platform": platform,
        },
    )


@login_required
@require_POST
def toggle_crt(request):
    profile = request.user.profile
    profile.crt_enabled = not profile.crt_enabled
    profile.save(update_fields=["crt_enabled"])
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"crt_enabled": profile.crt_enabled})
    return redirect(request.META.get("HTTP_REFERER", "dashboard"))
