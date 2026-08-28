# Architecture

## Auth boundaries (phase 1)

| Component | Auth |
|-----------|------|
| Control Center (this project) | Django users + sessions |
| File Share (:8096) | Legacy homelab-auth SQLite |
| URL Drop (:8092) | Legacy homelab-auth SQLite |
| Accounts (:8097) | Legacy homelab-auth admin |
| Other Docker apps | Their own auth or none |

Only apps **inside Django** share login. Cross-port SSO for legacy FastAPI apps is out of scope until those apps are migrated or proxied.

## Adding a mini-app (Addon)

Addons are Django apps bundled inside the Control Center. They share platform login and appear in the top navigation when enabled.

1. `python manage.py startapp myapp apps/myapp`
2. Set `name = "apps.myapp"` in `apps/myapp/apps.py`
3. Add `"apps.myapp"` to `INSTALLED_APPS`
4. Add URLs under `path("myapp/", include("apps.myapp.urls"))`
5. Register the addon in `library/catalog.py` (`ADDONS` list with `slug`, `url_name`, `url_prefix`)
6. Extend `templates/core/base.html` for app templates

The Library UI (superuser → **Library** → **Addons**) toggles visibility via `AddonState`. Disabled addons are removed from nav and return 404 on their URL prefix. No restart is required.

## Services vs Addons

| Type | What it is | Install action |
|------|------------|----------------|
| **Addon** | Django mini-app inside this project | **Install** in Library (enables nav + routes) |
| **Service** | Self-hosted app (Docker) | **Install** in Library (Docker deploy + auto dashboard card) |

Library services are installed via Docker on the Control Center host (`DOCKER_HOST`). The compose socket must be writable. `InstalledService` tracks container name, host port, and image version. Uninstall removes the container and dashboard card; optional data volume wipe.

`SiteSettings.services_host` is the LAN IP used for auto-created cards (auto-detected on first install).

Daily `check_service_updates` (or opportunistic check on Library/dashboard load) fetches GitHub releases for catalog repos. Library cards show the latest version; dashboard cards show an **Update** pill when a newer release exists.

## Public subdomains

Configure in `.env`:

```
HOST_APP_MAP=notes.thezaidan.family:notes
EXTRA_ALLOWED_HOSTS=notes.thezaidan.family
SESSION_COOKIE_DOMAIN=.thezaidan.family
```

Cloudflare tunnel hostname → `http://192.168.0.40:8099`

Mark views public with `@login_not_required` where needed.

## Theme

Design-only retro palette (no roleplay copy). CSS variables use `--tva-*` names internally. CRT overlay is user-toggleable.

## Database

SQLite with WAL mode in production. Back up `data/db.sqlite3` before upgrades.
