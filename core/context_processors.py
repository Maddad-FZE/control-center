from django.conf import settings

from .site_settings import get_site_settings
from .version import get_current_version


def site(request):
    site_settings = get_site_settings()
    crt_enabled = site_settings.crt_enabled
    user_theme = "wood"
    if request.user.is_authenticated and hasattr(request.user, "profile"):
        user_theme = request.user.profile.theme
    logo_url = None
    favicon_url = None
    if site_settings.logo:
        logo_url = site_settings.logo.url
    if site_settings.favicon:
        favicon_url = site_settings.favicon.url

    is_admin = request.user.is_authenticated and request.user.is_superuser
    nav_apps = []
    if request.user.is_authenticated:
        nav_apps = list(settings.NAV_APPS)
        if is_admin:
            nav_apps.append({"name": "Library", "url_name": "library", "icon": "library"})
            from library.addons import get_enabled_addon_nav_entries

            nav_apps.extend(get_enabled_addon_nav_entries())

    update_ready = False
    if is_admin:
        from .updates import update_available

        update_ready = update_available()

    return {
        "site_title": (site_settings.title or "").strip() or settings.SITE_TITLE,
        "site_tagline": (site_settings.tagline or "").strip(),
        "nav_apps": nav_apps,
        "crt_enabled": crt_enabled,
        "user_theme": user_theme,
        "site_logo_url": logo_url,
        "site_favicon_url": favicon_url,
        "weather_configured": bool(
            site_settings.weather_location
            and site_settings.weather_lat
            and site_settings.weather_lon
        ),
        "is_admin": is_admin,
        "app_version": get_current_version(),
        "update_available": update_ready,
    }
