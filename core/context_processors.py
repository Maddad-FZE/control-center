from django.conf import settings

from .site_settings import get_site_settings


def site(request):
    crt_enabled = True
    user_theme = "wood"
    if request.user.is_authenticated and hasattr(request.user, "profile"):
        crt_enabled = request.user.profile.crt_enabled
        user_theme = request.user.profile.theme
    site_settings = get_site_settings()
    logo_url = None
    favicon_url = None
    if site_settings.logo:
        logo_url = site_settings.logo.url
    if site_settings.favicon:
        favicon_url = site_settings.favicon.url
    return {
        "site_title": settings.SITE_TITLE,
        "nav_apps": settings.NAV_APPS,
        "crt_enabled": crt_enabled,
        "user_theme": user_theme,
        "site_logo_url": logo_url,
        "site_favicon_url": favicon_url,
        "weather_configured": bool(
            site_settings.weather_location and site_settings.weather_lat and site_settings.weather_lon
        ),
    }
