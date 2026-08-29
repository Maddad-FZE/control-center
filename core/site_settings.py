import logging

import requests
from django.core.cache import cache

from .models import SiteSettings

logger = logging.getLogger(__name__)

SITE_SETTINGS_CACHE_KEY = "site_settings_singleton"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


def get_site_settings():
    cached = cache.get(SITE_SETTINGS_CACHE_KEY)
    if cached is not None:
        return cached
    settings_obj = SiteSettings.load()
    cache.set(SITE_SETTINGS_CACHE_KEY, settings_obj, 300)
    return settings_obj


def clear_site_settings_cache():
    cache.delete(SITE_SETTINGS_CACHE_KEY)
    try:
        from library.addons import clear_addon_cache

        clear_addon_cache()
    except ImportError:
        pass


def geocode_location(location: str):
    if not location.strip():
        return None, None
    try:
        resp = requests.get(
            GEOCODE_URL,
            params={"name": location.strip(), "count": 1, "language": "en", "format": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            return None, None
        top = results[0]
        return top.get("latitude"), top.get("longitude")
    except Exception as exc:
        logger.warning("Geocoding failed for %s: %s", location, exc)
        return None, None


def update_weather_coordinates(settings_obj: SiteSettings):
    if not settings_obj.weather_location.strip():
        settings_obj.weather_lat = None
        settings_obj.weather_lon = None
        return
    lat, lon = geocode_location(settings_obj.weather_location)
    settings_obj.weather_lat = lat
    settings_obj.weather_lon = lon
