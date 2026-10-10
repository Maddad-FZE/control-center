"""Discover theme packs on disk and resolve the active one.

Resolution order: superuser (or first-run) session preview, then
SiteSettings.default_theme, then the bundled wood pack.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

FALLBACK_SLUG = "wood"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")
TOKEN_NAME_RE = re.compile(r"^--[a-z0-9-]{1,48}$")
MANIFEST_KEYS = frozenset(
    {
        "schema",
        "slug",
        "name",
        "extends",
        "min_app_version",
        "tokens",
        "layout",
        "helper",
        "dashboard",
        "supports_crt",
        "assets",
    }
)
CHROME = frozenset({"topbar", "sidebar", "none"})
FOOTER = frozenset({"visible", "hidden"})
HELPER_MODE = frozenset({"floating", "docked", "hidden"})
HELPER_DOCK = frozenset({"rail", "bottom"})
ARRANGEMENT = frozenset({"board", "launcher"})
STATS = frozenset({"sidebar", "drawer", "hidden"})

_packs = None


@dataclass
class Layout:
    chrome: str = "topbar"
    pinned: bool = True
    show_clock: bool = True
    footer: str = "visible"


@dataclass
class Helper:
    mode: str = "floating"
    dock: str = "rail"


@dataclass
class Dashboard:
    arrangement: str = "board"
    stats: str = "sidebar"


@dataclass
class Theme:
    slug: str
    name: str
    path: Path
    extends: str | None = None
    tokens: dict = field(default_factory=dict)
    layout: Layout = field(default_factory=Layout)
    helper: Helper = field(default_factory=Helper)
    dashboard: Dashboard = field(default_factory=Dashboard)
    supports_crt: bool = True
    assets_css: tuple = ()
    assets_js: tuple = ()
    chain: tuple = ()

    @property
    def static_dir(self):
        return self.path / "static"

    @property
    def templates_dir(self):
        return self.path / "templates"

    @property
    def token_css(self):
        parts = [f"{key}: {value};" for key, value in merged_tokens(self).items()]
        return " ".join(parts)

    @property
    def has_preview(self):
        preview = self.path / "preview.png"
        return preview.is_file() and not preview.is_symlink()


def theme_dirs():
    configured = getattr(settings, "THEME_DIRS", None)
    if configured:
        return [Path(p) for p in configured]
    base = Path(settings.BASE_DIR)
    return [base / "themes", base / "data" / "themes"]


def clear_theme_cache():
    global _packs
    _packs = None


def get_packs():
    global _packs
    if _packs is None:
        _packs = _discover()
    return _packs


def get_theme(slug):
    return get_packs().get(slug)


def _discover():
    found = {}
    for root in theme_dirs():
        if not root.is_dir() or root.is_symlink():
            continue
        root_real = root.resolve()
        for child in sorted(root.iterdir()):
            pack = _load_pack(child, root_real)
            if pack is None:
                continue
            if pack.slug in found:
                logger.warning("Theme %s ignored; slug already loaded", pack.slug)
                continue
            found[pack.slug] = pack
    _link_chains(found)
    if FALLBACK_SLUG not in found:
        logger.error("Bundled theme %r is missing", FALLBACK_SLUG)
    return found


def _contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def _load_pack(child: Path, root_real: Path):
    if not child.is_dir() or child.is_symlink():
        return None
    if not _contained(child, root_real):
        logger.warning("Theme dir escapes its root: %s", child)
        return None
    if not SLUG_RE.match(child.name):
        logger.warning("Theme dir name is not a valid slug: %s", child.name)
        return None
    manifest_path = child / "theme.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        logger.warning("Theme %s has no theme.json", child.name)
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Theme %s manifest unreadable: %s", child.name, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("Theme %s manifest is not an object", child.name)
        return None
    extra = set(data) - MANIFEST_KEYS
    if extra:
        logger.warning("Theme %s has unknown manifest keys: %s", child.name, sorted(extra))
        return None
    if data.get("schema") != 1:
        logger.warning("Theme %s schema is not 1", child.name)
        return None
    slug = data.get("slug")
    if slug != child.name or not isinstance(slug, str) or not SLUG_RE.match(slug):
        logger.warning("Theme %s slug does not match its folder", child.name)
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        logger.warning("Theme %s has no name", slug)
        return None
    extends = data.get("extends") or None
    if extends is not None and (not isinstance(extends, str) or not SLUG_RE.match(extends)):
        logger.warning("Theme %s extends is invalid", slug)
        return None
    if extends == slug:
        logger.warning("Theme %s extends itself", slug)
        return None
    tokens = _tokens(data.get("tokens") or {}, slug)
    if tokens is None:
        return None
    layout = _layout(data.get("layout") or {}, slug)
    helper = _helper(data.get("helper") or {}, slug)
    dashboard = _dashboard(data.get("dashboard") or {}, slug)
    if layout is None or helper is None or dashboard is None:
        return None
    assets = data.get("assets") or {}
    if not isinstance(assets, dict):
        logger.warning("Theme %s assets is not an object", slug)
        return None
    css = _asset_list(assets.get("css") or [], child / "static", slug)
    js = _asset_list(assets.get("js") or [], child / "static", slug)
    if css is None or js is None:
        return None
    supports = data.get("supports_crt", True)
    if not isinstance(supports, bool):
        logger.warning("Theme %s supports_crt is not a boolean", slug)
        return None
    min_version = data.get("min_app_version")
    if min_version is not None and not _version_ok(min_version):
        logger.warning("Theme %s requires app %s", slug, min_version)
        return None
    return Theme(
        slug=slug,
        name=name.strip(),
        path=child,
        extends=extends,
        tokens=tokens,
        layout=layout,
        helper=helper,
        dashboard=dashboard,
        supports_crt=supports,
        assets_css=tuple(css),
        assets_js=tuple(js),
    )


def _tokens(raw, slug):
    if not isinstance(raw, dict):
        logger.warning("Theme %s tokens is not an object", slug)
        return None
    clean = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not TOKEN_NAME_RE.match(key):
            logger.warning("Theme %s token name rejected: %s", slug, key)
            return None
        if not isinstance(value, str) or not value or len(value) > 80:
            logger.warning("Theme %s token value rejected: %s", slug, key)
            return None
        if any(ch in value for ch in ";{}<>\\\n\r"):
            logger.warning("Theme %s token value rejected: %s", slug, key)
            return None
        clean[key] = value
    return clean


def _choice(raw, key, allowed, slug, default):
    if key not in raw:
        return default
    value = raw[key]
    if value not in allowed:
        logger.warning("Theme %s %s is invalid", slug, key)
        return None
    return value


def _layout(raw, slug):
    if not isinstance(raw, dict):
        return None
    chrome = _choice(raw, "chrome", CHROME, slug, "topbar")
    footer = _choice(raw, "footer", FOOTER, slug, "visible")
    if chrome is None or footer is None:
        return None
    pinned = raw.get("pinned", True)
    show_clock = raw.get("show_clock", True)
    if not isinstance(pinned, bool) or not isinstance(show_clock, bool):
        logger.warning("Theme %s layout flags are invalid", slug)
        return None
    return Layout(chrome=chrome, pinned=pinned, show_clock=show_clock, footer=footer)


def _helper(raw, slug):
    if not isinstance(raw, dict):
        return None
    mode = _choice(raw, "mode", HELPER_MODE, slug, "floating")
    dock = _choice(raw, "dock", HELPER_DOCK, slug, "rail")
    if mode is None or dock is None:
        return None
    return Helper(mode=mode, dock=dock)


def _dashboard(raw, slug):
    if not isinstance(raw, dict):
        return None
    arrangement = _choice(raw, "arrangement", ARRANGEMENT, slug, "board")
    stats = _choice(raw, "stats", STATS, slug, "sidebar")
    if arrangement is None or stats is None:
        return None
    return Dashboard(arrangement=arrangement, stats=stats)


def _asset_list(items, static_dir, slug):
    if not isinstance(items, list):
        return None
    out = []
    for item in items:
        if not isinstance(item, str) or not item or item.startswith(("/", "\\")) or ".." in Path(item).parts:
            logger.warning("Theme %s asset path rejected: %s", slug, item)
            return None
        target = (static_dir / item)
        if target.is_symlink() or not target.is_file() or not _contained(target, static_dir.resolve()):
            logger.warning("Theme %s asset missing: %s", slug, item)
            return None
        out.append(item)
    return out


def _version_ok(required):
    if not isinstance(required, str):
        return False
    from core.version import get_current_version

    def parse(value):
        parts = []
        for piece in value.split("."):
            if not piece.isdigit():
                return None
            parts.append(int(piece))
        return tuple(parts)

    have = parse(get_current_version())
    need = parse(required)
    if have is None or need is None:
        return False
    return have >= need


def _link_chains(found):
    for pack in found.values():
        chain = []
        seen = set()
        current = pack
        while current is not None and current.slug not in seen:
            seen.add(current.slug)
            chain.append(current)
            if not current.extends:
                break
            parent = found.get(current.extends)
            if parent is None:
                logger.warning("Theme %s extends missing %s", pack.slug, current.extends)
                break
            current = parent
        pack.chain = tuple(chain)


def merged_tokens(theme: Theme) -> dict:
    """Parent tokens first, then the pack, so the child wins."""
    merged = {}
    for pack in reversed(theme.chain):
        merged.update(pack.tokens)
    return merged


def _site_default_slug():
    try:
        from core.site_settings import get_site_settings

        slug = (get_site_settings().default_theme or "").strip()
    except Exception:
        logger.debug("Site theme unavailable; using %s", FALLBACK_SLUG, exc_info=True)
        return ""
    return slug


def resolve_theme(request=None):
    """Pick the theme for this request. Never raises."""
    packs = get_packs()
    preview = _preview_slug(request, packs)
    if preview and preview in packs:
        return packs[preview]
    default = _site_default_slug()
    if default in packs:
        return packs[default]
    if FALLBACK_SLUG in packs:
        return packs[FALLBACK_SLUG]
    return Theme(slug=FALLBACK_SLUG, name="Wood & Orange", path=Path("."), chain=())


def _setup_in_progress():
    from django.core.cache import cache

    from core.middleware import SETUP_DONE_CACHE_KEY

    if cache.get(SETUP_DONE_CACHE_KEY):
        return False
    try:
        from django.contrib.auth.models import User

        if User.objects.exists():
            cache.set(SETUP_DONE_CACHE_KEY, True, None)
            return False
    except Exception:
        return False
    return True


def can_preview(request) -> bool:
    if request is None:
        return False
    from core.themes.authz import can_manage_theme

    user = getattr(request, "user", None)
    if can_manage_theme(user):
        return True
    return _setup_in_progress()


def _preview_slug(request, packs):
    if request is None or not can_preview(request):
        return None
    session = getattr(request, "session", None)
    if session is None:
        return None
    if request.method == "GET" and "theme" in request.GET:
        raw = (request.GET.get("theme") or "").strip().lower()
        if raw in ("", "off", "clear"):
            session.pop("theme_preview", None)
            return None
        if raw in packs:
            session["theme_preview"] = raw
            return raw
    stored = session.get("theme_preview")
    if stored in packs:
        return stored
    if stored:
        session.pop("theme_preview", None)
    return None


def theme_dirs_env():
    raw = os.environ.get("THEME_DIRS", "")
    if not raw.strip():
        return None
    return [part.strip() for part in raw.split(os.pathsep) if part.strip()]
