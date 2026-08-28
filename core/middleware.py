from django.conf import settings
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.urls import reverse


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
        if not User.objects.exists():
            path = request.path
            allowed_prefixes = (
                "/setup/",
                "/static/",
                settings.MEDIA_URL,
            )
            if not any(path.startswith(p) for p in allowed_prefixes):
                return redirect(reverse("setup"))
        return self.get_response(request)
