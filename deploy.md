# Deploy checklist (Raspberry Pi)

## Pre-deploy

- [ ] Copy project to Pi (or git clone)
- [ ] `cp .env.example .env` and set strong `SECRET_KEY`
- [ ] Set `DJANGO_SETTINGS_MODULE=config.settings.prod`
- [ ] Set `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SESSION_COOKIE_DOMAIN`
- [ ] Configure `NTFY_*` credentials
- [ ] `python manage.py check --deploy` passes

## Docker

```bash
docker compose build
docker compose up -d
docker compose exec control-center python manage.py migrate
docker compose exec control-center python manage.py seed_homelab
docker compose exec control-center python manage.py createsuperuser
docker compose exec control-center python manage.py collectstatic --noinput
```

## Cloudflare tunnel

Add public hostname:

- `control.thezaidan.family` → `http://192.168.0.40:8099` (optional dashboard)
- Per mini-app hostnames via `HOST_APP_MAP`

## Cutover from Homepage

1. Run platform on **8099** alongside Homepage **:80** for validation
2. `python manage.py seed_homelab --yaml /path/to/services.yaml` (optional import from Pi)
3. Copy logo to `static/img/logo.png`
4. Point `zaidan.home` tunnel/DNS to new app when satisfied
5. Stop Homepage container after validation period
6. Retire homelab-auth when File Share / URL Drop are migrated

## Releases and updates

The app reports the version in the `VERSION` file and compares it against the
latest GitHub release of `GITHUB_REPO`.

### Cutting a release

1. `python manage.py bump_version patch` (or `minor` / `major`, or `--set 0.2.0`)
   to write `VERSION` and roll `CHANGELOG.md` Unreleased into a dated heading
2. Commit, then `git tag v0.2.0 && git push origin main --tags`
3. Publish a GitHub release for the tag; the release body becomes the in-app notes

Preview without writing files: `python manage.py bump_version patch --dry-run`.

### Scheduled checks

Settings > Updates checks at most once every `UPDATE_CHECK_INTERVAL_HOURS`
(default 12) when an admin opens the pane. Add a cron entry so the check also
runs unattended:

```cron
0 */12 * * * cd /home/daher/control-center && .venv/bin/python manage.py check_updates >> data/update-check.log 2>&1
```

### Installing from the UI

The footer **Update available** button and Settings > Updates both open a
progress popup. Installing runs `git fetch`, `git checkout <tag>`,
`pip install -r requirements.txt`, `migrate`, `collectstatic`, then restarts
the service. A live log and step checklist update until the restart, then the
popup offers Reload.

Requirements and caveats:

- The deploy must be a **git checkout** with a clean working tree; installs abort
  if there are uncommitted changes
- Set `UPDATE_RESTART_COMMAND` (for example `sudo systemctl restart control-center`)
  or run under gunicorn, where the master is sent `SIGHUP` for a graceful reload
- Set `UPDATES_ALLOW_INSTALL=false` to disable in-app installs entirely
- The `build: .` compose setup bakes source into the image, so the in-app
  installer does not persist across container recreation. Either bind-mount the
  source or rebuild the image with `docker compose up -d --build` after tagging

## Backups

- Volume mount: `./data:/app/data`
- Backup `data/db.sqlite3` regularly

## SQLite production notes

- Gunicorn workers: **1** (or use PostgreSQL for multi-worker)
- WAL mode enabled automatically on connection

## Import Homepage YAML from Pi

```bash
scp daher@192.168.0.40:~/homepage/config/services.yaml /tmp/services.yaml
python manage.py seed_homelab --yaml /tmp/services.yaml
```
