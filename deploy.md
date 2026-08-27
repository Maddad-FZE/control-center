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
