"""Daily GitHub release checks for library catalog services."""

import logging
import threading

import requests
from django.core.cache import cache
from django.utils import timezone

from core.updates import _parse_published_at, is_newer

from .catalog import SERVICES, get_service_by_slug
from .models import CatalogRelease, InstalledService

logger = logging.getLogger(__name__)

GITHUB_API_ROOT = "https://api.github.com"
CHECK_LOCK_KEY = "catalog:version_check"
CHECK_LOCK_TTL = 300
CHECK_INTERVAL_SECONDS = 24 * 3600
REQUEST_TIMEOUT = 10


def _unique_repos():
    repos = []
    seen = set()
    for entry in SERVICES:
        repo = entry.get("repo", "").strip()
        if repo and repo not in seen:
            seen.add(repo)
            repos.append(repo)
    return repos


def _fetch_latest_release(repo):
    url = f"{GITHUB_API_ROOT}/repos/{repo}/releases/latest"
    headers = {"Accept": "application/vnd.github+json"}
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        return None, str(exc)[:255]
    if resp.status_code == 404:
        return _fetch_latest_tag(repo)
    if not resp.ok:
        return None, f"GitHub returned {resp.status_code}"
    try:
        payload = resp.json()
    except ValueError:
        return None, "Malformed GitHub response"
    version = (payload.get("tag_name") or "").strip()[:64]
    return {
        "latest_version": version,
        "release_url": payload.get("html_url") or "",
        "published_at": _parse_published_at(payload.get("published_at")),
    }, ""


def _fetch_latest_tag(repo):
    url = f"{GITHUB_API_ROOT}/repos/{repo}/tags"
    headers = {"Accept": "application/vnd.github+json"}
    try:
        resp = requests.get(
            url,
            headers=headers,
            params={"per_page": 1},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        return None, str(exc)[:255]
    if not resp.ok:
        return None, f"GitHub returned {resp.status_code}"
    tags = resp.json()
    if not tags:
        return {"latest_version": "", "release_url": "", "published_at": None}, ""
    tag = tags[0]
    version = (tag.get("name") or "").strip()[:64]
    return {
        "latest_version": version,
        "release_url": f"https://github.com/{repo}/releases/tag/{version}",
        "published_at": None,
    }, ""


def check_repo(repo):
    data, error = _fetch_latest_release(repo)
    row, _ = CatalogRelease.objects.get_or_create(repo=repo)
    row.checked_at = timezone.now()
    row.check_error = error or ""
    if data:
        row.latest_version = data.get("latest_version", "")
        row.release_url = data.get("release_url", "")
    row.save()
    return row


def check_all():
    for repo in _unique_repos():
        try:
            check_repo(repo)
        except Exception as exc:  # noqa: BLE001 - continue other repos
            logger.warning("Catalog release check failed for %s: %s", repo, exc)


def _check_worker():
    try:
        check_all()
    finally:
        cache.delete(CHECK_LOCK_KEY)


def maybe_check_daily():
    oldest = CatalogRelease.objects.order_by("checked_at").first()
    if oldest and oldest.checked_at:
        age = timezone.now() - oldest.checked_at
        if age.total_seconds() < CHECK_INTERVAL_SECONDS:
            return
    if not cache.add(CHECK_LOCK_KEY, "1", CHECK_LOCK_TTL):
        return
    thread = threading.Thread(target=_check_worker, name="catalog-version-check", daemon=True)
    thread.start()


def latest_version_for_repo(repo):
    row = CatalogRelease.objects.filter(repo=repo).first()
    return row.latest_version if row else ""


def service_has_update(slug, installed_version=""):
    entry = get_service_by_slug(slug)
    if not entry:
        return False
    row = CatalogRelease.objects.filter(repo=entry["repo"]).first()
    if not row or not row.latest_version:
        return False
    if not installed_version:
        inst = InstalledService.objects.filter(slug=slug).first()
        installed_version = inst.installed_version if inst else ""
    if not installed_version:
        return False
    return is_newer(row.latest_version, installed_version)


def update_map_for_services(service_rows):
    """Return {service_id: {latest, release_url}} for cards with catalog slugs."""
    slugs = [
        s.catalog_slug
        for s in service_rows
        if s.catalog_slug and getattr(s, "check_updates", True)
    ]
    if not slugs:
        return {}
    installed = {
        row.slug: row.installed_version
        for row in InstalledService.objects.filter(slug__in=slugs)
    }
    repos = {}
    for slug in slugs:
        entry = get_service_by_slug(slug)
        if entry:
            repos[slug] = entry["repo"]
    release_rows = {
        row.repo: row
        for row in CatalogRelease.objects.filter(repo__in=set(repos.values()))
    }
    result = {}
    for service in service_rows:
        if not service.catalog_slug or not service.check_updates:
            continue
        slug = service.catalog_slug
        repo = repos.get(slug)
        if not repo:
            continue
        row = release_rows.get(repo)
        if not row or not row.latest_version:
            continue
        installed_ver = installed.get(slug, "")
        if installed_ver and is_newer(row.latest_version, installed_ver):
            result[service.id] = {
                "latest": row.latest_version,
                "release_url": row.release_url,
            }
    return result
