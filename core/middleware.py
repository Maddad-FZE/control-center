from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse

SETUP_DONE_CACHE_KEY = "setup:has_users"


class HostAppMiddleware:
    """Route public mini-app hostnames to their dedicated URLconf."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0].lower()
        app_name = settings.HOST_APP_MAP.get(host)
        if app_name:
            request.urlconf = f"apps.{app_name}.urls_public"
        return self.get_response(request)


class AddonEnabledMiddleware:
    """Return 404 for disabled bundled addon URL prefixes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from library.addons import is_addon_enabled
        from library.catalog import ADDONS

        path = request.path
        for addon in ADDONS:
            prefix = addon.get("url_prefix", "")
            if prefix and path.startswith(prefix) and not is_addon_enabled(addon["slug"]):
                from django.http import Http404

                raise Http404("This addon is disabled.")
        return self.get_response(request)


class SetupRequiredMiddleware:
    """Redirect to first-run setup when no users exist."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if cache.get(SETUP_DONE_CACHE_KEY):
            return self.get_response(request)
        if User.objects.exists():
            cache.set(SETUP_DONE_CACHE_KEY, True, None)
            return self.get_response(request)
        path = request.path
        allowed_prefixes = (
            "/setup/",
            "/static/",
            settings.MEDIA_URL,
        )
        if not any(path.startswith(p) for p in allowed_prefixes):
            return redirect(reverse("setup"))
        return self.get_response(request)


class AccountGuardMiddleware:
    """Force 2FA enrolment and password change when required."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return self.get_response(request)
        path = request.path
        if path.startswith(("/static/", "/media/", "/sw.js")):
            return self.get_response(request)
        if path.startswith(("/logout/", "/login/")):
            return self.get_response(request)

        profile = getattr(user, "profile", None)
        if profile and profile.must_change_password:
            if not path.startswith(("/profile/", "/password/change/")):
                return redirect(reverse("profile") + "?section=security")

        from core.access import is_admin
        from core.site_settings import get_site_settings
        from core.totp import twofa_enabled

        site = get_site_settings()
        needs_2fa = bool(site.require_2fa_for_all) or (
            bool(site.require_2fa_for_admins) and is_admin(user)
        )
        if needs_2fa and not twofa_enabled(user):
            if not path.startswith(("/profile/", "/password/change/")):
                return redirect(reverse("profile") + "?section=security")

        return self.get_response(request)
