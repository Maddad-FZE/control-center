"""Hostname routing reference — wired via core.middleware.HostAppMiddleware."""

from django.conf import settings

DEFAULT_HOST = "localhost"
ROOT_HOSTCONF = "config.urls"

# Public mini-app hostnames are configured in settings.HOST_APP_MAP
PUBLIC_HOSTS = list(getattr(settings, "HOST_APP_MAP", {}).keys())
