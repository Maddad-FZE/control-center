# Changelog

All notable changes to the Homelab Control Center are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.1] - 2026-10-10

### Added

- Site-wide theme packs. Wood stays the default. Settings → Appearance sets the theme for everyone, with a session preview
- New builtin apps ship in `catalog/apps.json`. Library → **Update list** reads `Maddad-FZE/alef-app-catalog` and leaves Settings → Add app entries, plus any installed app the file no longer lists
- Settings → Updates channel: Stable stays on GitHub releases; Dev follows every commit on `UPDATE_DEV_BRANCH`
- Card menu **Troubleshoot**: check a service, offer one-button repairs for admins, and copy a redacted technical report
- Dashboard Stats starts collapsed to a right rail after sign-in; Tracked, Apps, and Misc stay expanded
- Library apps: Glances (host process list), Linkding, Stirling-PDF, IT-Tools, Wallos, Kavita, Changedetection.io, Open WebUI, BookStack, Odysseus, and Securo
- BookStack install creates a MariaDB sidecar and sets the public URL
- Odysseus install builds from Git and starts Chroma, SearXNG, and ntfy
- Securo install starts frontend, backend, Postgres, Redis, and Celery on a private network
- Library installer honors `pid: host` and `extra_hosts` from compose

### Fixed

- Wood dashboard keeps the footer at a fixed height and scrolls Stats inside the page. Merlin sits in his dock
- Actual Budget install sets the listen port, waits until the server is up, and falls back to GHCR if Docker Hub pull fails

## [0.4.0] - 2026-09-07

### Added

- Host bootstrap (`scripts/install.sh`): install Docker, write `.env`, and start Control Center with one command
- First-run setup asks for server name, tagline, logo, and favicon as well as the admin account
- Settings → **Logs**: tail Control Center and installed Docker service logs with source picker, keyword filter, live tail, and download
- Settings → **Console**: password-confirmed App and Host shells over WebSocket (superuser only)
- Settings → **Users**: create, edit, disable, and delete accounts with Admin / Member / Viewer roles and per-user service access
- Profile → **Security**: TOTP 2FA with recovery codes, optional site-wide enforcement, and console re-auth
- Profile → **Vault**: encrypted per-user credentials for later auto sign-in, with a console env hook (`CC_SVC_USER` / `CC_SVC_SECRET`)
- Rotating app log files under `data/logs/` (`app.log`, `tick.log`) with Docker log rotation in compose
- ASGI worker (`uvicorn`) for WebSocket console while keeping gunicorn as the process manager

### Changed

- Settings is a full-viewport board with numbered sections and field help tips
- Site secrets (Kuma password, Cloudflare tokens) are encrypted at rest
- Members see only public cards plus the services an admin assigns; viewers cannot acknowledge alerts
- Published cards open the public hostname; Open using IP in the card menu still goes to the LAN address
- Restart the server from the System panel (admin, confirmed)
- Restart Docker services from Containers, Library, and the card menu
- USB panel lists plugged-in devices; storage mounts can be unmounted
- Matter in the Library Home Automation catalog
- Library and catalog cards use the bundled icon list, then the original icon if there is no match
- Merlin swoops in on the first visit, then teleports or uses another entrance when you change pages
- Nextcloud Library install creates a Postgres sidecar and skips the setup wizard (admin username and password only)
- Settings → Platform → **Library repositories** editor to add, edit, or remove catalog entries (delete blocked while installed or data volumes remain)

### Fixed

- Library category filter dropdown uses dark background and cream text (readable on all platforms)
- Dashboard cards no longer show offline when health is unknown; only explicit down checks mark a service red
- A finished previous install no longer blocks the next update (old 100% bar, log, and Reload popup)
- Confirm, alert, and prompt dialogs use Control Center chrome instead of browser popups
- Apps cards open on click again after hold-to-reorder changes
- Delete card removes from the dashboard without a full page reload
- Merlin only waves on idle when there are unacknowledged alerts

## [0.3.1] - 2026-08-30

- Library Cloudflare Tunnel install, token link in Settings, and explicit publish/unpublish
- Publishing Control Center (port 80, or legacy 8099) is blocked so the dashboard stays on the LAN

### Fixed

- Cloudflare token link uses Tunnel (`argotunnel`) + All accounts/zones, and finds the account from DNS when `/accounts` is empty
- Tunnel Settings starts with Connect, then Link account, and maps Cloudflare auth failures to a tunnel-permission hint
- Publish online opens as a centered popup on the dashboard as well as Library
- Publish hostname field is subdomain-only; the Cloudflare zone is shown and not editable
- Tunnel origins are host:port only (no path), so Pi-hole `/admin/` and similar cards can be published
- Settings → Tunnel shows an install prompt until Cloudflare Tunnel is installed

## [0.3.0] - 2026-08-30

### Added

- Open dashboard services in an overlay under the header, with Back, new tab, and Always open in a new tab
- Card kebab **Open in overlay** for every viewer
- Merlin hover bubbles for Tips, Alerts, and Update when those actions exist on the page
- Search the library catalog by name, description, or slug
- Open button on installed library services
- Generated Uptime Kuma admin (`cc-monitor`) with Show and Copy in Settings
- Monitor empty state with an Install Uptime Kuma button that opens Library filtered to Kuma
- Library search reads `?q=` so Monitor can deep-link to Uptime Kuma

### Fixed

- In-app update streams pip output so Dependencies does not look stuck
- Docker installs reload gunicorn with SIGHUP instead of calling a missing `docker` CLI
- A dead update worker is marked failed instead of leaving the UI on “running”
- Merlin clips finish instead of being cut off by the next timer
- Merlin no longer plays the idle lightbulb animation
- Deleting a dashboard card also removes its Uptime Kuma monitor
- Always open in a new tab also opens the service immediately
- Monitor shows waiting, not the install CTA, while Kuma is installing or syncing

### Changed

- Install runs as `manage.py install_update` outside the gunicorn request worker
- Docker: in-app update is for bind-mounted or current-container overlays; image rebuild is the durable path
- Health checks pull Uptime Kuma monitor status instead of pinging cards from Control Center
- Monitor kicks the first Kuma sync from the dashboard if tick has not run yet
- Uptime (24h) panel renamed to Monitor
- Uptime Kuma is opt-in from Library; tick no longer installs it or adds a dashboard card
- Library Add card is a compact + control; uninstall defaults to deleting data volumes

## [0.2.1] - 2026-08-30

### Changed

- Background `tick` owns health pings and GitHub checks so the dashboard only reads cache
- Dashboard polling pauses when the tab is hidden and matches cache intervals

### Fixed

- Library install maps Nextcloud (and other 80/9000 listeners) to the port the image actually serves

## [0.2.0] - 2026-08-29

### Added

- Header update chip to the left of weather; it appears only when a release is available and shakes every 7 seconds

### Changed

- In-app updates download the GitHub release archive instead of requiring a git checkout
- Install keeps `data/`, `.env`, and `media/` in place, then migrates and restarts

## [0.1.2] - 2026-08-29

### Added

- Optional Merlin wizard with page tips and spoken site messages
- Site settings to call in the wizard and let him notify instead of toasts
- Misc chips with edit, visibility, and delete (bookmarks migrate to services)
- Weather and clock in the header for guests, using the server timezone
- Clickable Up filter (`is:up`) alongside Down
- Red status lights flash while a health check is in progress

### Changed

- Down cards fade instead of using a hazard stripe
- Misc kebab sits beside the icon and stays vertically centered
- Weather API is public so guests see the same site location

## [0.1.1] - 2026-08-29

### Added

- One-click update popup with live progress bar, step checklist, and install log
- `manage.py bump_version` to roll VERSION and CHANGELOG for a release
- Library install popup with indeterminate progress while Docker pulls
- Card URLs prefer the LAN host used to open the site (not Docker bridge IPs)
- Full-page card editor with service search/dropdown, icon library, live-stats column, and footer save
- Guest status bar, site title/tagline settings, toast notifications, and public branding files
- Versioned CSS/JS so the UI stays fast without flashing stale designs

## [0.1.0] - 2026-08-28

### Added

- Retro wood/orange dashboard with live service health checks and widgets
- Guest, user, and admin roles with public/private service cards
- In-app card management (add, edit, delete, visibility) for admins
- First-run setup wizard
- Settings screen with appearance, site branding, users, and platform sections
- Version reporting, GitHub release checks every 12 hours, and in-app updates
