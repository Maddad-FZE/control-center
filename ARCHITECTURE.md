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

## Adding a mini-app

1. `python manage.py startapp myapp apps/myapp`
2. Set `name = "apps.myapp"` in `apps/myapp/apps.py`
3. Add `"apps.myapp"` to `INSTALLED_APPS`
4. Add URLs under `path("myapp/", include("apps.myapp.urls"))`
5. Add nav entry to `NAV_APPS` in settings
6. Extend `templates/core/base.html`

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
