# Homelab Control Center

Django platform for the Zaidan homelab: dashboard, shared auth, retro theme, and mini-apps.

**Workspace:** `/home/dzaidan/control-center`  
**Dev URL:** http://127.0.0.1:8000/  
**Pi URL (when deployed):** http://192.168.0.40:8099/

## Quick start (WSL)

```bash
cd /home/dzaidan/control-center
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_homelab
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/ and sign in.

## Features

- Retro wood/orange dashboard (CRT toggle per user)
- Service tiles with live health checks
- System stats (psutil) and Docker container list
- Alerts + ntfy push on service down (configure `.env`)
- Audit log in Settings (filter, search, pagination)
- App library: unified grid of Addons and Services with Install/Uninstall, version badges, and daily update checks
- One-click Docker install for catalog services (auto port, auto dashboard card)
- Notes mini-app example (first bundled addon)
- Public subdomain routing for mini-apps (Cloudflare tunnel)
- Version reporting with GitHub release checks every 12 hours and one-click updates from Settings

## Updates

The current version lives in `VERSION` and is shown in the footer. Settings >
Updates (and the footer **Update available** button) compare it against the
latest GitHub release and install that release archive in place. A git
checkout is not required.

```bash
python manage.py check_updates          # respects the 12h throttle
python manage.py check_updates --force  # check immediately
python manage.py check_service_updates  # daily catalog release check (cron-friendly)
python manage.py bump_version patch --dry-run   # preview VERSION + CHANGELOG bump
python manage.py bump_version patch             # write files, then tag and push
```

See [deploy.md](deploy.md) for the release process and cron setup.

## Legacy apps (phase 1)

**File Share**, **URL Drop**, and **Accounts** remain separate Docker apps with their own auth until rewritten as Django apps. They appear as dashboard tiles only.

See [ARCHITECTURE.md](ARCHITECTURE.md) for auth boundaries and adding new apps.

## Pi deploy

See [deploy.md](deploy.md).
