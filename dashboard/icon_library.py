"""Search the bundled Simple Icons library used across Library and cards."""

import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from library.catalog import SERVICES
from library.icons import simpleicons_slug

ICON_CDN = "https://cdn.simpleicons.org/"


@lru_cache(maxsize=1)
def all_simpleicons():
    path = Path(settings.BASE_DIR) / "static" / "data" / "simpleicons.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def icon_url(slug):
    return f"{ICON_CDN}{slug}/E87722"


def featured_slugs():
    slugs = []
    seen = set()
    for entry in SERVICES:
        slug = simpleicons_slug(entry["slug"])
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def search_simpleicons(query="", limit=420):
    icons = all_simpleicons()
    by_slug = {row["slug"]: row for row in icons}
    if not query:
        featured = []
        for slug in featured_slugs():
            row = by_slug.get(slug) or {"title": slug, "slug": slug}
            featured.append(row)
        featured_set = {i["slug"] for i in featured}
        rest = [row for row in icons if row["slug"] not in featured_set]
        return (featured + rest)[:limit]
    needle = query.strip().lower()
    hits = [
        row
        for row in icons
        if needle in row["title"].lower() or needle in row["slug"]
    ]
    return hits[:limit]


def slug_from_icon_url(url):
    if not url or "simpleicons.org/" not in url:
        return ""
    part = url.split("simpleicons.org/", 1)[1]
    return part.split("/")[0].split("?")[0].strip()
