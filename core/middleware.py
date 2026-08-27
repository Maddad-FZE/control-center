from django.conf import settings


class HostAppMiddleware:
    """Route public subdomains to mini-app URLconfs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw_host = request.META.get("HTTP_HOST", "")
        host = raw_host.split(":")[0].lower()
        app_name = settings.HOST_APP_MAP.get(host)
        if app_name:
            request.host_app = app_name
            if app_name == "notes":
                request.urlconf = "apps.notes.urls_public"
        else:
            request.host_app = None
        return self.get_response(request)
