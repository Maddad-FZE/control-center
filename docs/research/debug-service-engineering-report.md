# Debug Service — Engineering Research Report

**Status:** RESEARCH ONLY. This document specifies a card-level Debug Service. It does **not** implement the feature.

**Repo snapshot:** `main` at research time (2026-09-12). All `VERIFIED` citations refer to this tree.

**Companion file:** [`docs/research/debug-service-catalog.json`](debug-service-catalog.json) — machine-readable `issues` (75), `actions` (30), `probes` (18), `service_types`, `permissions`, `report_fields`, `implementation_files`, `open_questions` (10). Extra keys `unsafe_actions_must_not_exist` and `meta` are documentation aids.

**How to read this document**

- **VERIFIED** = current code behavior with path, symbol, and line range.
- **PROPOSED** = design for the implementing agent. Not present in the repo today.
- Facts and recommendations are labeled separately. Do not treat a recommendation as existing behavior.
- Do not claim a repair is safe unless this report records a data-loss and rollback analysis.
- Restart is not a universal fix. Reboot the Pi only after narrower actions fail.

---

## Executive findings (facts first)

1. **There is no Debug Service today.** Card menus, Library, health ticks, Kuma, and Cloudflare already expose fragments of diagnosis and repair, but nothing correlates them into a per-card pipeline.
2. **A changed host port is not reconciled across copies.** Detection writes `InstalledService.host_port` for *unmanaged* containers only. Dashboard `Service.port` / `href` / `health_check_url` / `widget_url`, Kuma monitors, Cloudflare `TunnelRoute.origin_url`, widget caches, and app env vars (`APP_URL`, `FRONTEND_URL`, `NEXTCLOUD_TRUSTED_DOMAINS`) are separate stores. Most are never updated together after first install.
3. **`Service.save()` is a silent overwrite machine.** When `host` and `port` are both set, `save()` rebuilds `href`, always sets `widget_url` to `http://{host}:{port}`, and rewrites `health_check_url` if it is empty or contains `/admin`. Any future “sync port” that calls `save()` without `update_fields` will clobber customized widget/health URLs.
4. **Detection currently cannot run.** `library/detect.py` calls `get_docker_spec()` but does not import it. `maybe_sync_detected()` only swallows `docker.errors.DockerException`, so a `NameError` aborts `manage.py tick` after health/prune/update checks. There are **no detect tests**.
5. **“Admin” in the UI means Django superuser, not `UserProfile.role=admin`.** Product text says “repairs are admin-only.” Existing mutating APIs gate on `request.user.is_superuser`. `core.access.is_admin()` also treats `profile.role == "admin"` as admin. That mismatch is an open product decision.
6. **Managed stacks can be recreated while keeping named volumes** if the implementing agent follows the existing install workers (they `_ensure_volume` / ignore “already exists,” and reuse previous DB passwords). Blind volume/image/log deletes must never be offered.
7. **Current HTTP health is coarse.** `_check_url_once` treats any status `< 500` as up, including 401/403/404. Debug must not reuse that verdict as “the app is healthy.”

---

## A. Existing architecture (VERIFIED)

### A.1 Django apps and entry points

| Area | Path | Role |
|------|------|------|
| Dashboard cards, health, widgets, host ops | `dashboard/` | `Service`, `ServiceCheck`, `Alert`; HTTP/Kuma health; widget fetch; card CRUD |
| Library catalog, Docker install, detect, tunnel | `library/` | `CatalogItem`, `InstalledService`, `TunnelRoute`; install/uninstall/restart; Cloudflare |
| Auth, settings, logs, updates, vault | `core/` | `SiteSettings`, `AuditEvent`, `UserProfile`, `VaultEntry` |
| Notes addon | `apps/notes/` | Bundled Django mini-app, not a Docker service |
| URL mount | `config/urls.py` | `""` → core + dashboard; `"library/"` → library; `"notes/"` → notes |

Tick sidecar (`docker-compose.yml` 29–50): container `control-center-tick` runs `python manage.py tick` every 60s with the Docker socket mounted.

### A.2 Service / card model

`dashboard.models.Service` (`dashboard/models.py` 27–167):

| Field | Lines | Meaning |
|-------|-------|---------|
| `category` | 33–35 | FK `ServiceCategory` |
| `name`, `description` | 36–37 | Display |
| `href` | 38 | Open URL; **rebuilt on save** when host+port exist |
| `host`, `port`, `path` | 39–41 | LAN address parts. `path` default `"/"` |
| `icon`, `logo` | 42–43 | Icon URL or uploaded file |
| `health_check_url` | 44 | Optional; blank skips HTTP fallback |
| `is_public`, `is_misc`, `enabled` | 45–51 | Visibility / Misc bucket / enabled |
| `widget_type` | 52–56 | `none` / `pihole` / `speedtest` |
| `widget_url` | 57 | Widget API base; **overwritten on save** when host+port exist |
| `widget_api_key` | 58 | Pi-hole app password / API bearer |
| `catalog_slug` | 59–63 | Library link; blank for custom cards |
| `check_updates` | 64–67 | Update-pill eligibility |
| `kuma_monitor_id` | 68 | Uptime Kuma monitor id |

Related:

- `ServiceMetric` (170–185): generic widget JSON paths.
- `ServiceCheck` (202–211): `checked_at`, `is_up`, `response_ms`, `error` (max 255).
- `Alert` (213–225): down/recovery banners.
- `Bookmark` (188–199): leftover model; bookmarks were migrated to misc services (`dashboard/migrations/0007_bookmarks_to_misc_services.py`).

**`Service.save()` address rebuild** (`dashboard/models.py` 87–126):

1. `_sync_from_widget_url()` (87–95): if `host` empty and `widget_url` set, copy hostname/port from widget URL.
2. If `host` and `port` are both set:
   - Pi-hole with path `/` → force `path = "/admin/"`.
   - `href = http://{host}:{port}{path}`.
   - `widget_url = http://{host}:{port}` (**always**, even if a deeper widget path was stored).
   - `health_check_url` rewritten to `{base}/admin/` if empty **or** if current value contains `"/admin"`.
3. Else: `href = build_href()`; if health URL empty, copy `href`.

**Implication (fact):** any Debug “sync card from Docker port” that assigns `service.port` and calls `service.save()` will reset widget and often health URLs. Use `update_fields` and an explicit preserve/overwrite policy (PROPOSED, §D).

`build_href()` (97–105): host+port wins; else widget netloc + path; else stored `href`.

`display_icon` (128–142) / `display_description` (153–167): catalog icon/blurb overlay. Not address data.

### A.3 InstalledService and catalog

`library.models.InstalledService` (`library/models.py` 16–44):

| Field | Meaning |
|-------|---------|
| `slug` (unique) | Catalog slug |
| `container_name` | Primary container (usually `cc-{slug}`) |
| `host_port` | Published host port; `0` for tunnel / installing |
| `status` | `installing` / `running` / `stopped` / `error` |
| `managed` | `True` = Control Center created it; `False` = detected |
| `error` | Last install error, truncated to 500 chars in workers |
| `installed_version` | Image label/tag |

`CatalogItem` (98–145): DB-backed catalog. `to_entry()` omits `container_port` unless non-zero. Seeded from `library/catalog.py` `SERVICES` via `catalog_store.ensure_catalog_seeded()` (64–68).

`get_docker_spec(entry)` (`library/catalog.py` 826–893): line-oriented compose parser (not PyYAML despite `PyYAML` in `requirements.txt`). Extracts first `image:`, `"host:container"` port pair, volume *container* paths (skips absolute host binds), environment, `pid:`, `extra_hosts`. Returns `image`, `container_port`, `host_port_hint`, `volumes`, `env`, `pid_mode`, `extra_hosts`.

**Compose gaps (VERIFIED):** Immich compose is a comment (`catalog.py` 259); Paperless compose is a comment (496). Install of those slugs fails with “No Docker image configured” (`installer.py` 887–892) unless a custom `CatalogItem` supplies real compose.

Special catalog flags:

- `install_options: "admin-credentials"` — Nextcloud only (`catalog.py` 469).
- `NO_CARD_ON_INSTALL = {"uptime-kuma", "cloudflare-tunnel"}` (`installer.py` 90–91).
- `DOCKER_LABEL_SLUG = "control-center.slug"`; `DOCKER_LABEL_ROLE = "control-center.role"` (30–31).

### A.4 Multi-container stacks (managed)

| Slug | Frontend container | Sidecars | Network | Volumes preserved on recreate | Port-dependent env |
|------|--------------------|----------|---------|-------------------------------|--------------------|
| `nextcloud` | `cc-nextcloud` | `cc-nextcloud-db` | `cc-nextcloud-net` | `cc-nextcloud-0`, `cc-nextcloud-db-0` | `NEXTCLOUD_TRUSTED_DOMAINS`, admin wait URL |
| `bookstack` | `cc-bookstack` | `cc-bookstack-db` | `cc-bookstack-net` | `cc-bookstack-0`, `cc-bookstack-db-0` | `APP_URL` |
| `odysseus` | `cc-odysseus` | chroma, searxng, ntfy | `cc-odysseus-net` | data + sidecar vols | sidecar URLs are *internal* DNS names |
| `securo` | `cc-securo` | backend, db, redis, worker, beat | `cc-securo-net` | db + attachments + knowledge + embeddings | `FRONTEND_URL` on frontend **and** backend |

Install workers: `_install_nextcloud` 393–464, `_install_bookstack` 494–567, `_install_odysseus` 595–671, `_install_securo` 714–821. Generic single-container path: `_install_worker` 877–997.

**Recreate semantics (VERIFIED):** workers call `_remove_container` then `containers.run` with the same volume names. `_ensure_volume` / `volumes.create` ignore “already exists” (`installer.py` 304–308, 943–949). Previous Postgres/MariaDB/Securo secrets are read from the **old** container env *before* remove (`_previous_container_env` 319–325). **Fact:** named-volume data survives a managed recreate. **Fact:** bind-mount `./` compose paths are **not** used at runtime — installer only mounts named `cc-{slug}-{idx}` volumes to the container path. Host `./config` in catalog compose is documentation, not the live bind.

**Sidecar restart gap:** Library restart (`library/views.py` 160–177) and card restart (`card-menu.js` 147–169 → `/api/docker/restart/`) restart **only** `InstalledService.container_name`. Sidecars are not restarted. Uninstall does remove sidecars (`installer.py` 1049–1061).

### A.5 Installation, detection, update, restart, uninstall

**Install** — `library.views.api_service_install` (110–137) → `installer.start_install` (1000–1038):

- Superuser only.
- Rejects if status is `running`/`stopped` (“Already installed”) or `installing`.
- Sets `managed=True`, `status=installing`, `container_name=cc-{slug}`, `host_port=0`.
- Background daemon thread `_install_worker`.
- Nextcloud requires JSON `admin_user` / `admin_password`.
- UI polls `/library/api/services/<slug>/status/` every 2s up to 120 times (`static/js/library.js` 202–221).

**Detection** — `library/detect.py`:

- `sync_detected_services` (137–188): list all containers; skip if label `control-center.slug` present (`_match_container_to_slug` 97–100 returns `None` for CC-labeled containers); match image repo / slug tail / name; skip if an `InstalledService` exists with `managed=True` (153–154); upsert unmanaged row; delete unmanaged rows whose containers vanished.
- `_host_port_from_container` (68–85): prefer catalog container port binding; else first TCP `HostPort`.
- Throttle: cache lock `library:detect_sync` + file `data/detect.stamp`, TTL 900s (17–19, 191–202).
- Invoked from `tick` (`dashboard/management/commands/tick.py` 32) and `manage.py detect_installed`.

**VERIFIED defect:** `get_docker_spec` is called at `detect.py` 54 and 132 but never imported. `maybe_sync_detected` (205–213) catches only `DockerException`. First detect after stamp expiry raises `NameError` and fails the tick process. No tests reference `sync_detected_services` (grep of `*tests.py` is empty).

**Detection does not touch dashboard cards, Kuma, or tunnels.** It only writes `InstalledService`. Library “Add card” (`library/_card.html` 57–59) is a manual link to `/cards/new/?catalog=`.

**Update (catalog versions):** `library/versions.py` daily GitHub release check (`catalog:version_check` lock). Dashboard shows an “Update Available” banner (`_service_card.html` 20–22) from `update_map_for_services`. **There is no one-click service image update API.** Control Center *app* updates are a separate Settings flow (`core/updates.py`).

**Restart:**

- Library: `POST /library/api/services/<slug>/restart/` → `hostops.restart_container(row.container_name)` (`library/views.py` 160–177).
- Dashboard card / Docker panel: `POST /api/docker/restart/` with `{name}` (`dashboard/views.py` 523–542; `hostops.py` 242–256). Name must match `CONTAINER_NAME_RE` `^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,126}$`. Timeout 20s. Invalidates `docker:containers`.
- Confirmation copy: `Restart {name}? It will be briefly offline.` (`card-menu.js` 150–153; `library.js` 228–231; `dashboard.js` 681–684).

**Uninstall** — `installer.uninstall` (1041–1094):

- Stops/removes primary + known sidecars.
- If `remove_data`: deletes volumes named `cc-{slug}-*`, labeled with slug, or (unmanaged only) currently mounted volume names (`_remove_service_volumes` 269–285).
- Removes stack networks.
- Tunnel slug also `unlink_account(delete_remote=False)`.
- `delete_dashboard_card` removes Kuma monitors then cards (865–874).
- UI (`library.js` 137–148): `remove_data` checkbox **defaults checked**. Copy warns unmanaged containers will be stopped and removed. This is **destructive** and already exists — Debug must not add a quieter path.

### A.6 Health checks and ServiceCheck history

Constants (`dashboard/services.py` 22–31): `CHECK_THROTTLE_SECONDS=50`, `HEALTH_TIMEOUT=3`, `CHECK_RETENTION_HOURS=48`, cache TTLs 15–60s, lock `health:tick_lock` for 55s.

Probe path:

1. `probe_service_health(service)` (208–221): URL = `health_check_url or href`; `_check_url` (HEAD then GET on ≥400, retry once on failure); create `ServiceCheck`; side effects; delete `health:results` and `uptime:payload`.
2. `_check_url_once` (139–149): `is_up = status_code < 500`. **401/403/404 count as up.**
3. `run_health_checks` (272–326): if `HEALTH_CHECK_ENABLED`; `kuma.pull_status()`; if Kuma returns rows, write checks (throttled); services with `kuma_monitor_id` and no heartbeat keep last status; others HTTP-probe.
4. `maybe_run_health_tick` (329–332): cache.add lock.
5. `prune_old_checks` (335–341): delete checks older than 48h.
6. Alerts: second consecutive down creates `Alert` + `log_audit("service_down")` + ntfy (`_apply_health_side_effects` 224–249). Recovery creates success alert + `service_up` audit. **ntfy is not sent on recovery.**

API: `GET /api/health/` → `get_cached_health()` (no live probe). Dashboard polls every 45s (`dashboard.js` 823–827, 902).

### A.7 Uptime Kuma

`dashboard/kuma.py`:

- Presence: `InstalledService` slug `uptime-kuma` (`kuma_is_present` 35–44). Running requires `host_port > 0` (27–32).
- URLs: container IP `:3001` first, then LAN `http://{services_host}:{host_port}` (`kuma_api_urls` 59–86).
- Client: `uptime-kuma-api` `UptimeKumaApi` (timeout 8). Tests inject `set_client_factory` (21–24).
- Creds: `SiteSettings.kuma_username` / encrypted `kuma_password`; generated as `cc-monitor` + `token_urlsafe(18)` on first setup (157–172).
- `sync_monitors` (252–304): one HTTP monitor per enabled `Service` with non-empty `href`, excluding Kuma itself. Interval 60. Match by `kuma_monitor_id` then URL. `edit_monitor` if URL or name changed. **Monitors track `href`, not `health_check_url`.**
- `pull_status` (382–398): ensure running (may start a stopped container — 89–101, 104–115), connect, sync, read heartbeats.
- Delete: `delete_monitor_for_service` on card delete (418–428) and `delete_monitors_for_services` on catalog uninstall (865–873).
- **Kuma is never auto-installed** (`ensure_kuma_installed` 104–115). Official Kuma Socket.IO API is internal/unsupported ([wiki](https://github.com/louislam/uptime-kuma/wiki/Internal-API), accessed 2026-09-12). Repo uses the Python wrapper `add_monitor` / `edit_monitor` / `delete_monitor` / `get_heartbeats` ([uptime-kuma-api docs](https://uptime-kuma-api.readthedocs.io/en/stable/api.html), accessed 2026-09-12). Uptime Kuma 2.3.2 can reject clients that omit `conditions` ([PR 7484](https://github.com/louislam/uptime-kuma/pull/7484)); if a future Kuma upgrade breaks sync, Debug should surface that as infra, not as the target service.

### A.8 Cloudflare tunnel

`library/cloudflare.py` + `TunnelRoute` (`library/models.py` 62–74: `hostname`, `catalog_slug`, `service_id`, `origin_url`).

- Link/unlink/publish/unpublish: Settings + Library + card menu. Superuser APIs in `library/views.py` 211–318.
- Connector: `start_connector` (305–333) recreates `cc-cloudflare-tunnel` with `TUNNEL_TOKEN`. `host_port` stays 0. Control Center publish is blocked (`is_control_center_target` 349–375; ports `{80, 8099}`).
- `ingress_origin` (390–412): **scheme://host:port only, no path.** If hostname is on the tunnel zone, rewrite host to `services_host()`, scheme http, port from catalog `default_port`.
- `origin_for_service` (415–453): prefers `Service.host`/`port`, else href, else `services_host` + `host_port` / catalog default.
- `_sync_ingress` (456–472): PUT `/accounts/{id}/cfd_tunnel/{id}/configurations` with all routes + `{service: http_status:404}`. Official API: [Create a tunnel (API)](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel-api/) and [Update tunnel configuration](https://developers.cloudflare.com/api/resources/zero_trust/subresources/tunnels/subresources/cloudflared/subresources/configurations/) (accessed 2026-09-12). Repo uses the older `/cfd_tunnel/` path; Cloudflare docs now also document Zero Trust `cloudflared` configuration resources. Behavior matches: replace entire ingress list, catch-all required.
- DNS: proxied CNAME `{tunnel_id}.cfargotunnel.com`.
- Dashboard open URL: `_apply_publish_urls` (`dashboard/views.py` 44–54) sets `open_href = public_href or lan`. Public is `https://{hostname}{path}{query}` (`public_href` 533–543).

**Fact:** changing `Service.port` does **not** update `TunnelRoute.origin_url` unless publish is run again. `_sync_ingress` only normalizes `ingress_origin` of stored origins.

HTTP seam for tests: `set_http_session` (41–44).

### A.9 Widget URLs and caches

Server cache keys (`dashboard/services.py`):

| Key | TTL | Writer / invalidator |
|-----|-----|----------------------|
| `system:stats` | 15s | `get_system_stats` |
| `docker:containers` | 15s | `get_docker_containers`; deleted on restart |
| `health:results` | 15s | health functions |
| `uptime:payload` | 60s / 15s | Kuma payload; deleted on health write / Kuma install |
| `alerts:recent` | 15s | alerts; deleted on ack |
| `health:tick_lock` | 55s | tick lock |
| `widget:{type}:{url}:{key}` | 45s + stale 3600s | per-widget |
| `pihole:sid:{base}:{sha256[:16]}` | session validity | Pi-hole v6 SID |
| `widgets:bundle:{public_only}` / `widgets:bundle:ids:{ids}` | 30s + stale 3600s | bundle |
| `weather:{lat}:{lon}` | 900s | weather |
| `usb:devices` | 15s | hostops |
| `host:reboot_lock` | 90s | reboot |
| `site_settings_singleton` | 300s | site settings |
| `library:detect_sync` | 900s | detect |
| `catalog:version_check` | 300s | versions |
| `logs:{source}:{tail}:{since}:{query}` | 3s | log tail |
| `addon:disabled_slugs` / `addon:nav_entries` | 300s | addons |
| `setup:has_users` | forever | middleware |

Client: `localStorage` prefix `cc-dash:v1:` (`static/js/dashboard-cache.js` 1–41), keys `system`, `docker`, `alerts`, `health`, `uptime`, `widgets`, `usb`, max age 24h. **Port changes do not bust client cache** until TTL/reload.

Widget fetch (`fetch_service_widget` 775–820): Pi-hole v6 `/api/auth` + `/api/stats/summary`, v5 `/admin/api.php`; Speedtest several `/api/speedtest/*`; generic GET `widget_url` with `X-API-Key` + `Authorization: Bearer`.

Pi-hole launch (`library/pihole.py` 131–144): `browser_url` uses **the Control Center request host** + `service.port`, not `service.host`. Auto-login sets non-HttpOnly `sid` cookie (`dashboard/views.py` 237–247).

### A.10 Docker API access

- Client: `docker.DockerClient(base_url=settings.DOCKER_HOST)` default `unix:///var/run/docker.sock` (`config/settings/base.py` 175; `installer.get_docker_client` 106–107; `hostops._docker_client` 53–54; `services.get_docker_containers` 115).
- Compose bind: `/var/run/docker.sock` on both `control-center` and `tick` (`docker-compose.yml` 22, 46).
- Official Engine inspect: `GET /containers/{id}/json` → `NetworkSettings.Ports` is `PortMap` of `containerPort/proto` → `[{HostIp, HostPort}]`; `HostConfig.RestartPolicy.Name` is `""` / `no` / `always` / `unless-stopped` / `on-failure` ([Docker Engine API](https://docs.docker.com/reference/api/engine/), [docker-py containers](https://docker-py.readthedocs.io/en/stable/containers.html), accessed 2026-09-12).
- Repo uses docker-py high-level: `containers.list(all=True)`, `.get(name)`, `.restart(timeout=20)`, `.start()`, `.stop(timeout=15)`, `.remove(force=True)`, `.logs(tail, timestamps)`, `.exec_run`, `images.pull`, `volumes.create/list/remove`, `networks.create/get/remove`.
- `get_docker_containers` (110–136) does **not** return ports — only name, image, status, slug label. Debug port discovery must inspect attrs (as detect already does).

**Socket ≈ root (fact):** any Debug action that accepts a container name must reuse `CONTAINER_NAME_RE` and an allowlist (installed names + labeled `control-center.slug`), never raw user strings into the API without validation. Existing restart already validates the name regex (`hostops.py` 17, 242–245).

### A.11 Host statistics and operations

`get_system_stats` (57–107): `psutil.cpu_percent(interval=None)`, `virtual_memory`, `disk_partitions` skipping `PSEUDO_FSTYPES` (32–51), `sensors_temperatures` first reading, `boot_time`, `net_io_counters`. Official psutil: [cpu_percent](https://psutil.readthedocs.io/latest/api.html#psutil.cpu_percent), [virtual_memory](https://psutil.readthedocs.io/latest/api.html#psutil.virtual_memory), [disk_usage](https://psutil.readthedocs.io/latest/api.html#psutil.disk_usage), [sensors_temperatures](https://psutil.readthedocs.io/latest/api.html#psutil.sensors_temperatures) (accessed 2026-09-12). **Note:** `cpu_percent(interval=None)` returns since last call; module calls it once at import (54) so the first request after process start is meaningful.

Reboot: `POST /api/system/reboot/` superuser (`views.py` 473–486) → `schedule_reboot` (359–364): lock 90s, timer 2s, then `HOST_REBOOT_COMMAND` or sysrq `b` or `systemctl reboot` / `reboot` / `shutdown -r now` or privileged Docker helper (`hostops.py` 336–356). Ubuntu `systemctl reboot` is orderly; `--force` twice can lose data ([Ubuntu systemctl man](https://manpages.ubuntu.com/manpages/xenial/man1/systemctl.1.html), accessed 2026-09-12). Raspberry Pi OS also uses systemd ([Pi systemd docs](https://github.com/raspberrypi/documentation/blob/83aeab3278fc7b648022fb56b30e4d62c5ccba24/linux/usage/systemd.md), accessed 2026-09-12). Existing UI: `templates/dashboard/index.html` 181–188, copy “This reboots the whole machine.”

USB list/unmount exist; out of scope for Debug except as “host storage full / unmounted media” context.

### A.12 Logs and audit

Settings logs (`core/logs.py`): file sources `app` / `tick`; Docker sources = `control-center`, `control-center-tick`, plus every `InstalledService.container_name` matching `CONTAINER_NAME_RE`. Tail cap 1000 lines, 256 KiB payload, 5s Docker timeout. APIs superuser-only (`core/views.py` 363–401). **Sidecar names are not listed unless they are the primary `container_name`.** Debug log probe must inspect labeled containers, not only `list_sources()`.

Audit: `core.models.log_audit` (227–245) → `AuditEvent` types include `admin`, `service_down`, `service_up`, `app`, `console`, `user`, `2fa`, `vault`. Existing Docker restart audits `Restarted container {name}` (`dashboard/views.py` 536–541). Library restart audits `Restarted {slug}` (171–176). **PROPOSED:** add `debug` event type or reuse `admin` with metadata `{action_id, service_id, incident_id, risk}`.

### A.13 Card dropdowns, modals, progress, copy, permissions

Card kebab (`templates/dashboard/_card_menu.html` 1–34): Open overlay, Open new tab, Open using IP (if published), Restart (admin + `container_name`), Credentials, Make public/private, Edit card, Publish/Unpublish, Delete card. **No Debug item.**

`is_admin` in dashboard view (`views.py` 77) is `request.user.is_superuser`, not `core.access.is_admin`. Restart/delete/visibility require that.

JS (`static/js/card-menu.js`): CSRF from `<meta name="csrf-token">` (only rendered when authenticated — `templates/core/base.html` 8–10). Confirm via `window.ccDialog.confirm`. Escape closes menus (202–204). Dropdown portaled to `document.body`.

Shared dialog (`static/js/cc-dialog.js`): alert / confirm / prompt; Escape; focus OK or field; `danger` styles confirm button; optional typed `expected` string. Reuse this for disruptive Debug confirms.

Progress patterns:

- Library install: indeterminate bar (`templates/library/index.html` 94–105, `updates.css` progress classes).
- App update: determinate `%` + step label + log `<pre>` (`templates/core/_update_modal.html`, `static/js/updates.js`).
- **PROPOSED Debug modal should follow the update modal (steps + log + copy) plus ccDialog confirms.**

Copy: `navigator.clipboard.writeText` with “Copied” flash (`static/js/settings-tabs.js` 61–78). Fallback: focus/select field.

Permissions matrix (VERIFIED):

| Action | Gate |
|--------|------|
| View dashboard / public cards | `@login_not_required` + `visible_service_ids` (`core/access.py` 41–52) |
| Health/widgets APIs | health: login; widgets: login_not_required but filtered |
| Card create/edit/delete/visibility/reorder | `is_superuser` |
| Docker restart / host reboot / USB unmount | `is_superuser` |
| Library install/uninstall/restart/catalog/tunnel | `is_superuser` |
| Logs / console / users | `is_superuser` |
| Ack alerts | `can_ack_alerts` = authenticated and not viewer (72–75) |
| Open overlay | `can_open_service` |
| `UserProfile.role` admin/member/viewer | used for visibility and ack; **not** for Library/Docker mutations |

`LoginRequiredMiddleware` is global (`base.py` 52). CSRF middleware is on (49). All existing POSTs send `X-CSRFToken`.

### A.14 Tick / background maintenance

`dashboard/management/commands/tick.py` 14–37:

1. `updates.recover_stale_install()`
2. `services.maybe_run_health_tick()`
3. `services.prune_old_checks()`
4. `updates.maybe_check_for_update()`
5. `library.versions.maybe_check_daily(background=False)`
6. `library.detect.maybe_sync_detected()`

Compose loop: `while true; do python manage.py tick; sleep 60; done`.

**PROPOSED:** Debug must not block tick. Optional cheap port-drift snapshot during detect (after detect import is fixed) is phase 1, not a full diagnosis.

### A.15 Tests and mock seams (VERIFIED)

| Class | File | Seam |
|-------|------|------|
| `HealthQueryTests` | `dashboard/tests.py` 17 | ServiceCheck queries |
| `OverlayViewTests` | 56 | cards, publish, reorder, prefs |
| `KumaHealthTests` + `FakeKuma` | 268, 326 | `kuma.set_client_factory` |
| `CardMenuPortalTests` | 632 | kebab DOM |
| `HostOpsTests` | 774 | reboot lock, `restart_container` name regex, USB |
| `PiholeLaunchTests` | 871 | launch cookie |
| `DockerSpecPortTests` | `library/tests.py` 29 | `get_docker_spec` ports |
| `DashboardCardTests` | 72 | `create_dashboard_card` |
| `CloudflareTunnelTests` | 176 | `cf.set_http_session` |
| `NextcloudInstallTests` / `Bookstack` / `Odysseus` / `Securo` | 516+ | `MagicMock` Docker client |
| `PiholeInstallTests` | 786 | vault + widget key |
| `CatalogApiTests` | 715 | catalog CRUD |
| `SettingsLogsConsoleTests` | `core/tests.py` 349 | log source validation |
| `UsersAccessTwoFAVaultTests` | 423 | roles, vault |

**Missing seams to add (PROPOSED):** detect; port reconcile; Debug views; SSRF URL guard; report redaction. Reuse `set_client_factory`, `set_http_session`, `patch("library.installer.get_docker_client")`, `patch("dashboard.hostops._docker_client")`, `patch("core.logs._docker_available")`.

### A.16 Current-state data-flow map (every copy of host / port / scheme / path)

```
                    ┌─────────────────────────────────────────┐
                    │ SiteSettings.services_host              │
                    │ env SERVICES_HOST / request host        │
                    │ installer.detect_services_host()        │
                    └───────────────┬─────────────────────────┘
                                    │ used at card create / origin rewrite
┌──────────────┐   inspect Ports    ┌──────────────┐  create_dashboard_card
│ Docker       │ ─────────────────► │ Installed    │ ─────────────────────►
│ HostPort     │   detect (unmgr)   │ Service.     │   Service.host/port
│ binding      │   install worker   │ host_port    │   href / path
└──────────────┘                    └──────────────┘   widget_url
       │                                   │           health_check_url
       │ managed install only              │           (save() rebuilds)
       │                                   │
       │                            NOT synced on detect refresh
       │
       ▼
 CatalogItem.default_port / container_port / path / compose
       │
       ├─► ServiceForm.clean() for linked cards (forms.py 251–271)
       ├─► origin_for_service catalog_port fallback (cloudflare.py 438–450)
       └─► Library lan_href = http://{services_host}:{host_port}/  (views.py 67–68)
                                                              ▲ always path /
┌──────────────┐  kuma sync_monitors (href)   ┌──────────────┐
│ Service.href │ ───────────────────────────► │ Kuma monitor │
│              │  health fallback if no Kuma  │ .url         │
│ health_url   │ ───────────────────────────► │ HTTP probe   │
│ widget_url   │ ───────────────────────────► │ widget cache │
└──────┬───────┘                              └──────────────┘
       │ origin_for_service / publish
       ▼
 TunnelRoute.origin_url  →  Cloudflare ingress (no path)
       │
       ▼
 open_href = https://{published_hostname}{path}   or   lan href
 launch_href = /view/{id}/launch/ for Pi-hole autologin

 App env (managed stacks only, set at install):
   Bookstack APP_URL=http://{services_host}:{host_port}
   Securo FRONTEND_URL=http://{services_host}:{host_port}
   Nextcloud NEXTCLOUD_TRUSTED_DOMAINS="{host} {host}:{port} localhost"
   Odysseus sidecar URLs are docker-network DNS (not LAN port)

 Client: localStorage cc-dash:v1:{health,widgets,...}
 Service worker: cc-shell-* / cc-static-* (HTML/CSS/JS only; APIs network-first)
```

**Authoritative value per service type (VERIFIED current practice, not a design):**

| Type | Authoritative port today | Authoritative host today | Path |
|------|--------------------------|--------------------------|------|
| Managed Docker | `InstalledService.host_port` after install; card copied once | `SiteSettings.services_host` at card create | catalog `path` |
| Detected unmanaged | `InstalledService.host_port` refreshed by detect (if detect worked) | same, only if user adds a card later | catalog `path` if they use Add card |
| Custom LAN / URL | `Service.host`/`port`/`path` parsed from `open_url` (`forms.py` 236–250) | URL hostname | URL path |
| Published card | LAN fields above; public hostname in `TunnelRoute` | public host is CF; origin should be LAN | path kept on public href only |
| Addon (Notes) | Django URL, not a card port | N/A | `/notes/` |

**Drift points (VERIFIED):**

1. Detect refresh of `host_port` ≠ `Service.port`.
2. `Service.save()` overwrites `widget_url` / sometimes `health_check_url`.
3. `create_dashboard_card` **deletes** existing cards for the slug (831) — reinstall wipes customizations, metrics, vault links (SET_NULL), kuma id.
4. Kuma URL = `href` only; health URL can differ (Pi-hole `/admin/`).
5. Tunnel origin ignores path; may use catalog `default_port` instead of live `host_port` when origin host looks like the CF zone (`ingress_origin` 400–409).
6. Library `lan_href` always `/`.
7. Pi-hole `browser_url` uses CC request host, not `service.host`.
8. Widget/health caches keyed by old URL.
9. Client `localStorage` stale health/widgets.
10. Managed env vars (`APP_URL`, `FRONTEND_URL`, `NEXTCLOUD_TRUSTED_DOMAINS`) frozen at last install.
11. `ServiceForm` hides host/port/path/health/widget fields (`service_form.html` 10–20). Users cannot fix port in the card editor without switching to Custom link.
12. Multi-binding: detect/install use a single preferred TCP port; extra published ports are ignored.
13. `get_docker_containers` cache has no ports for the dashboard Docker panel.

---

## B. Exhaustive issue catalog

Full records (probes, confidence, confirmation language, rollback, report fields) live in `debug-service-catalog.json` → `issues[]`. Summary by category:

### B.1 Address / metadata drift

| ID | Symptom | Auto-detect | Auto-repair | Risk |
|----|---------|-------------|-------------|------|
| `ISSUE_PORT_CARD_DRIFT` | Card opens wrong port; health hits old port | Yes (Docker vs Service.port) | Yes — sync card + linked URLs | Safe if preserve custom health/widget |
| `ISSUE_PORT_INSTALLED_DRIFT` | Library badge ≠ Docker | Yes | Yes — update InstalledService | Safe |
| `ISSUE_HOST_STALE` | Card uses old LAN IP after DHCP/host change | Yes vs `services_host()` | Yes — refresh host on linked cards | Safe; confirm if custom host |
| `ISSUE_HREF_DESYNC` | `href` ≠ host+port+path | Yes | Yes via controlled save | Safe |
| `ISSUE_HEALTH_URL_STALE` | Health still on old port | Yes | Yes unless user-customized | Safe with preserve rule |
| `ISSUE_WIDGET_URL_STALE` | Widget empty / wrong | Yes | Yes unless customized | Safe with preserve |
| `ISSUE_KUMA_URL_STALE` | Kuma monitor URL ≠ href | Yes if Kuma connected | Yes — `edit_monitor` | Safe |
| `ISSUE_TUNNEL_ORIGIN_STALE` | Public site 502/wrong app | Yes vs `origin_for_service` | Yes — `_sync_ingress` | Disruptive (public) |
| `ISSUE_ENV_PUBLIC_URL_STALE` | Nextcloud/Bookstack/Securo redirect to old port | Yes — inspect container Env | Disruptive recreate or env rewrite | Disruptive; preserve volumes |
| `ISSUE_CACHE_STALE` | UI shows old up/stats after fix | After any address change | Yes — delete keys | Safe |
| `ISSUE_CLIENT_CACHE_STALE` | Guest/admin see old widgets | After repair | Instruct reload; optional cache-bust query | Safe |
| `ISSUE_LIBRARY_LAN_PATH` | Library Open ignores `/admin/` | Yes for slugs with catalog path | N/A to Debug card (Library bug) | Manual |
| `ISSUE_DETECT_BROKEN` | Detect never refreshes ports | Yes — import error / tick log | Fix import (separate from Debug) | N/A |
| `ISSUE_FORM_CANNOT_EDIT_PORT` | User cannot fix port in editor | Linked cards hide port | Open editor as Custom or Debug sync | Manual |
| `ISSUE_MULTIPLE_BINDINGS` | Ambiguous published ports | Yes — >1 HostPort | Surface conflict, do not guess | Manual |
| `ISSUE_FRONTEND_AMBIGUOUS` | Stack has several published ports | Yes | Prefer labeled frontend / catalog port | Manual if tie |
| `ISSUE_SAVE_OVERWRITE` | Bare `Service.save()` clobbers `widget_url` | Static (code) | Use `update_fields` only | N/A — engineering trap |
| `ISSUE_PARTIAL_SYNC` | Card updated; Kuma/CF still old | After repair | Retry linked URL sync | Safe |

### B.2 HTTP / reachability

| ID | Notes |
|----|-------|
| `ISSUE_HTTP_CONN_REFUSED` | TCP closed. Distinct from HTTP 5xx. |
| `ISSUE_HTTP_TIMEOUT` | 3s current timeout is short for cold starts (Nextcloud 300s install wait). Debug HTTP budget 8s. |
| `ISSUE_DNS_FAIL` | Custom hostname / mDNS |
| `ISSUE_HTTP_5XX` | App up, erroring |
| `ISSUE_HTTP_401_403` | **Current health marks these UP.** Debug must classify as reachable-but-auth, not down. |
| `ISSUE_HTTP_404` | Wrong path (`/admin/` vs `/`) |
| `ISSUE_REDIRECT_LOOP` | APP_URL / trusted domains mismatch |
| `ISSUE_REDIRECT_OFF_LAN` | HTTPS redirect to public host while probing LAN |
| `ISSUE_EMPTY_HEALTH_URL` | No URL → skipped forever |

### B.3 TLS

Use `ssl.create_default_context()` ([Python ssl](https://docs.python.org/3/library/ssl.html), accessed 2026-09-12). Do not disable verification to “make it green.”

| ID | Typical cause |
|----|----------------|
| `ISSUE_TLS_EXPIRED` | Let’s Encrypt on NPM/Traefik |
| `ISSUE_TLS_HOSTNAME` | IP in URL vs cert CN |
| `ISSUE_TLS_UNTRUSTED` | Homelab CA / self-signed |
| `ISSUE_TLS_PROTOCOL` | Old TLS only |
| `ISSUE_TLS_HTTP_ON_443` | Scheme mismatch |

Custom cards with `https://` are the main TLS surface. Managed catalog installs use `http://` LAN.

### B.4 Docker

| ID | Repair |
|----|--------|
| `ISSUE_DOCKER_UNAVAILABLE` | None — explain socket |
| `ISSUE_CONTAINER_MISSING` | Recreate managed; manual unmanaged |
| `ISSUE_CONTAINER_EXITED` | Start |
| `ISSUE_CONTAINER_PAUSED` | Unpause (new) |
| `ISSUE_CONTAINER_RESTARTING` | Wait + logs; not restart-storm |
| `ISSUE_RESTART_POLICY_NO` | Restore `unless-stopped` (managed) |
| `ISSUE_OOM_KILLED` | Host memory; do not loop-restart |
| `ISSUE_PORT_NOT_PUBLISHED` | Correct binding (managed recreate) |
| `ISSUE_WRONG_NETWORK` | Reconnect known `cc-{slug}-net` |
| `ISSUE_IMAGE_MISSING` | Retry pull (managed) |
| `ISSUE_INSTALL_ERROR` | Show `InstalledService.error`; retry install |

### B.5 Multi-container dependencies

| ID | Stack |
|----|-------|
| `ISSUE_SIDECAR_EXITED` | Any special stack |
| `ISSUE_DB_NOT_READY` | Nextcloud/Bookstack/Securo |
| `ISSUE_REDIS_DOWN` | Securo |
| `ISSUE_BACKEND_DOWN` | Securo frontend up, API down |
| `ISSUE_STACK_ORDER` | Restart DB → cache → backend → frontend |

Restart-in-order is **disruptive**, not safe. Confirmation required. Volumes untouched.

### B.6 Host / Pi resources

Thresholds **PROPOSED** (not in code): CPU ≥ 95% sustained, memory ≥ 90%, disk ≥ 95%, temp ≥ 80°C (Pi throttle ~80–85°C is vendor guidance; treat as warning, not auto-reboot).

| ID | Action |
|----|--------|
| `ISSUE_HOST_CPU` | Explain; no auto-kill |
| `ISSUE_HOST_MEMORY` | Explain OOM; reboot last |
| `ISSUE_HOST_DISK` | Explain; **never** auto-prune unused images/volumes |
| `ISSUE_HOST_TEMP` | Explain; reboot last |
| `ISSUE_HOST_DOCKER_DISK` | Manual; do not `docker system prune` automatically |

### B.7 Application configuration

| ID | Service |
|----|---------|
| `ISSUE_NEXTCLOUD_TRUSTED_DOMAINS` | Trusted domain error page |
| `ISSUE_BOOKSTACK_APP_URL` | Redirect/asset wrong host |
| `ISSUE_SECURO_FRONTEND_URL` | CORS / redirects |
| `ISSUE_PIHOLE_PASSWORD` | Widget 401; vault vs container |
| `ISSUE_PIHOLE_PATH` | `/` vs `/admin/` |
| `ISSUE_GLANCES_PID` | Missing `pid_mode=host` |
| `ISSUE_OPENWEBUI_GATEWAY` | Missing `host.docker.internal` / Ollama not on host |
| `ISSUE_CATALOG_NO_IMAGE` | Immich/Paperless compose is a comment — “No Docker image configured” |

Env regeneration requires container recreate for most images (env is start-time). **Disruptive.** Preserve volumes/secrets as install workers do.

### B.8 Control Center infrastructure

| ID | Notes |
|----|-------|
| `ISSUE_TICK_DOWN` | `control-center-tick` not running → stale health |
| `ISSUE_KUMA_STOPPED` | Start existing container only |
| `ISSUE_KUMA_LOGIN` | Creds missing / Kuma already has other admin |
| `ISSUE_CF_CONNECTOR_DOWN` | `start_connector` (recreates connector; token from settings) |
| `ISSUE_CF_NOT_LINKED` | Manual Settings |
| `ISSUE_HEALTH_DISABLED` | `HEALTH_CHECK_ENABLED=false` |
| `ISSUE_DETECT_NAMEERROR` | Import bug |

### B.9 External / manual-only

Routers, ISP, Wi-Fi AP, vendor cloud, expired ISP modem, port-forward, CGNAT, client DNS, browser extension, service’s own broken config UI. Debug explains and offers **Open card / Open using IP / Copy report**. No Docker repair.

| ID | Manual explanation |
|----|--------------------|
| `ISSUE_EXT_ROUTER_FIREWALL` | Another device’s firewall / AP isolation |
| `ISSUE_EXT_SERVICE_APP_BUG` | App 5xx with container healthy |
| `ISSUE_EXT_UPSTREAM_DNS` | Public DNS / registrar |
| `ISSUE_EXT_ISP_CGNAT` | No inbound; tunnel is the path |
| `ISSUE_EXT_CLIENT_DNS` | This browser’s DNS/VPN; offer Open using IP |
| `ISSUE_EXT_EXPIRED_UPSTREAM_CERT` | Remote cert expired; CC will not write it |
| `ISSUE_EXT_LICENSE_UPSTREAM` | Vendor SaaS; do not probe arbitrary APIs |

---

## C. Solution and action registry

Full action records: JSON `actions[]`. Grouped reusable solutions:

### C.1 Safe (one click, no confirm) — PROPOSED

| ID | Reuses | Never if |
|----|--------|----------|
| `ACTION_RECHECK` | `probe_service_health`, widget fetch, optional Docker inspect | Diagnosis already running |
| `ACTION_DISCOVER_PORT` | detect `_host_port_from_container` + catalog port | Docker down; no container |
| `ACTION_CLEAR_CACHES` | delete keys in §A.9 | — |
| `ACTION_REFRESH_HOST` | `services_host()` + update card host if card host was previous services_host | Custom card host differs and user didn’t confirm |
| `ACTION_RESYNC_KUMA` | `kuma.sync_monitors` / `edit_monitor` | Kuma absent; service is Kuma |
| `ACTION_UPDATE_LINKED_URLS` | Card auto URLs + Kuma; optional CF via confirm action | Non-auto custom health/widget |
| `ACTION_SYNC_CARD_PORT` | `apply_address_sync` + `update_fields` | Multiple HostPorts; custom URLs |
| `ACTION_OPEN_*` | existing URLs (edit, logs, vault, settings, overlay, library) | — |

`ACTION_SYNC_CARD_PORT` is **safe** only when: single unambiguous Docker HostPort; health/widget URLs were auto-derived (same host:oldport prefix); user did not customize them. Otherwise promote to confirm.

### C.2 Disruptive (confirm) — PROPOSED

| ID | Blast radius | Rollback |
|----|--------------|----------|
| `ACTION_START` | One container | Stop if we started and verify fails? Prefer leave running |
| `ACTION_UNPAUSE` | One container | Pause again |
| `ACTION_RESTART` | Existing `restart_container` — brief outage | None (restart again) |
| `ACTION_RESTART_STACK` | All labeled `control-center.slug={slug}` in role order | None |
| `ACTION_RESTORE_RESTART_POLICY` | `HostConfig` update | Restore previous policy |
| `ACTION_RECONNECT_NETWORK` | Disconnect/connect known `cc-{slug}-net` | Reconnect previous |
| `ACTION_REPAIR_TUNNEL_ORIGIN` | Public ingress rewrite | Previous origin_url |
| `ACTION_REGEN_ENV` | Recreate frontend with new APP_URL etc. | Recreate with old env; volumes kept |
| `ACTION_CORRECT_PORT_BINDING` | Recreate with new `-p` | Recreate old binding; volume kept |
| `ACTION_RETRY_INSTALL` | `_install_worker` | Leaves ERROR row |
| `ACTION_RESTART_TICK` | Restart `control-center-tick` | — |
| `ACTION_RESTART_KUMA` | Restart Kuma container | — |
| `ACTION_RESTART_CF` | `start_connector` **recreates** connector | Token unchanged |

### C.3 Destructive (typed confirm) — PROPOSED, offer only when unavoidable

| ID | Confirmation | Preservation |
|----|--------------|--------------|
| `ACTION_RECREATE_MANAGED` | Type service name. “Named volumes and database passwords are kept. Container filesystem not in a volume is lost.” | Volumes + previous env secrets |
| `ACTION_REBOOT_HOST` | Existing reboot modal. Last resort after Docker + host-resource explanation | Entire machine |

**Do not implement `ACTION_UNINSTALL` inside Debug.** Send the user to Library. Uninstall already defaults to wipe volumes in the Library modal.

### C.4 Unsafe cleanup — MUST NOT EXIST

The following actions must not be implemented, suggested as default, or run without a separately designed product (they are not part of Debug):

- Blind `docker volume rm` / “clear data to fix it”
- `docker system prune -a` / unused image delete
- Delete `ServiceCheck` history to “fix” graphs
- Delete vault secrets
- `remove_data=True` uninstall from Debug
- Truncate container logs as a repair
- Rewrite unmanaged Compose files on disk
- Overwrite a user-custom `health_check_url` / `widget_url` whose host:port is **not** the old auto value
- Guess among multiple HostPorts
- Auto-reboot because CPU is high
- Publish or change a Cloudflare hostname the user did not already publish
- `exec` arbitrary commands into containers (Pi-hole `setpassword` already exists for a dedicated flow; do not generalize)

### C.5 Action properties (common)

**Idempotent:** recheck, cache clear, kuma sync (edit if needed), discover port, start (already running = success), unpause (already unpaused = success).

**Not idempotent:** recreate, reboot, regen env (new container id).

**Locking:** per-service cache lock `debug:lock:{service_id}` TTL 120s. Reject concurrent repair with 409.

**Cooldown:** same action 30s (`debug:cd:{service_id}:{action_id}`).

**Audit:** `log_audit("admin", message=f"Debug {action_id} on {service.name}", service=name, action_id=..., incident_id=..., risk=...)`.

**Permissions:** all repairs `is_superuser` (or `is_admin` if product chooses). Diagnosis read: `can_open_service` for the report body; repair buttons hidden for others.

---

## D. Port reconciliation design (PROPOSED)

### D.1 Authoritative sources

```
function authoritative_address(service):
    inst = InstalledService.objects.filter(slug=service.catalog_slug).first()
    catalog = get_service_by_slug(service.catalog_slug) if service.catalog_slug else None

    if inst and docker_available:
        container = inspect(inst.container_name) or inspect_by_label(slug)
        bindings = tcp_host_ports(container)
        chosen = pick_binding(bindings, catalog.container_port or catalog.default_port)
        host = services_host() if not is_custom_unlinked(service) else service.host
        return Source.DOCKER, host, chosen.port, catalog.path or service.path, chosen.confidence

    if inst and inst.host_port:
        return Source.INSTALLED, services_host(), inst.host_port, catalog.path or service.path, "stale_if_no_docker"

    if service.host and service.port:
        return Source.CARD, service.host, service.port, service.path, "card"

    parsed = urlparse(service.href or service.widget_url)
    return Source.URL, parsed.hostname, parsed.port, parsed.path, "href"
```

`is_custom_unlinked`: `not service.catalog_slug` (custom LAN/router/URL). Docker is never authoritative for those.

### D.2 Docker binding → card matching

Reuse detect’s `_host_port_from_container` once `get_docker_spec` is imported.

```
def pick_binding(bindings, preferred_container_port):
    if preferred_container_port and bindings.get(f"{preferred}/tcp"):
        hosts = unique HostPort list
        if len(hosts) == 1: return hosts[0], HIGH
        return None, CONFLICT
    tcp = all tcp HostPorts
    if len(tcp) == 1: return tcp[0], MEDIUM
    if len(tcp) == 0: return None, MISSING
    return None, CONFLICT  # never guess
```

Frontend identification for stacks:

1. Label `control-center.role` absent or `frontend` / unnamed primary `cc-{slug}`.
2. Else container that publishes `catalog.container_port`.
3. Else conflict.

### D.3 Preserving customized URLs

A URL is **auto-derived** if it equals one of:

- `http://{old_host}:{old_port}`
- `http://{old_host}:{old_port}{catalog_path}`
- `http://{old_host}:{old_port}/admin/` (Pi-hole)
- current `href` built from old host+port+path

```
def rewrite_if_auto(url, old_host, old_port, new_host, new_port):
    if not url: return url, False
    if is_auto_derived(url, old_host, old_port):
        return replace_netloc(url, new_host, new_port), True
    return url, False  # preserve
```

**Never call `Service.save()` without `update_fields`.** `save()` always resets `widget_url` to base (`models.py` 117).

### D.4 Propagation set (when applying a port/host change)

Transaction boundary: Django DB updates first; external systems after commit; compensate on failure.

1. `InstalledService.host_port` (if slug linked).
2. `Service.host`, `Service.port` (and `path` only if still catalog default).
3. `href` if auto.
4. `health_check_url` if auto.
5. `widget_url` if auto.
6. `TunnelRoute.origin_url` via `origin_for_service` + `_sync_ingress` if a route exists.
7. `kuma.sync_monitors` / `edit_monitor` if `kuma_monitor_id` or Kuma present.
8. Invalidate server caches (§A.9) including widget keys for **old and new** URLs and Pi-hole SID keys for old base.
9. Managed env: if Bookstack/Securo/Nextcloud env contains old `host:port`, offer `ACTION_REGEN_ENV` (not silent).
10. Client: return `cache_bust: true` so JS drops `cc-dash:v1:*` for health/widgets.

### D.5 When to detect

| Moment | Behavior |
|--------|----------|
| Debug start | Always inspect Docker if available |
| Tick / detect | After detect import fix: if unmanaged `host_port` changed, **do not** silently rewrite cards (product: surface next Debug or a future drift badge). **OPEN:** silent tick sync vs Debug-only. Recommendation: Debug-only apply; tick may store `debug:last_ports` cache for faster diagnosis. |
| Install / update worker | Already writes card via `create_dashboard_card` (destructive replace — do not reuse for Debug sync). |
| Manual card edit | Form currently overwrites from catalog/installed (`forms.py` 251–271). If user picks Custom URL, that URL wins. |

### D.6 Externally managed Compose

If `managed=False`:

- Read bindings; update `InstalledService`; offer sync **card** URLs.
- **Do not** recreate container, change binds, rewrite compose, or remove volumes.
- Restart is allowed with confirm (existing).

### D.7 Proposed interfaces

```python
# library/debug_ports.py  (PROPOSED new module)

@dataclass
class AddressSnapshot:
    source: str  # docker|installed|card|href
    host: str
    port: int | None
    path: str
    scheme: str
    bindings: list[dict]  # {container_port, host_port, proto}
    conflict: str  # "" | multiple_bindings | missing_container | docker_down
    confidence: str  # high|medium|low

def inspect_live_address(service: Service) -> AddressSnapshot: ...

def diff_addresses(service: Service, snap: AddressSnapshot) -> list[Finding]: ...

def apply_address_sync(
    service: Service,
    snap: AddressSnapshot,
    *,
    preserve_custom_urls: bool = True,
    update_tunnel: bool = True,
    update_kuma: bool = True,
    update_host: bool = False,
    actor=None,
) -> SyncResult: ...

def invalidate_service_caches(service: Service, old_urls: list[str]) -> None: ...
```

Rollback: keep previous field dict; on Kuma/CF failure after DB commit, write finding `ISSUE_PARTIAL_SYNC` and offer retry. Do not silently revert the card (user already wanted the new port).

---

## E. Diagnostic engine design (PROPOSED)

### E.1 Ordered bounded pipeline

```
diagnose(service_id, *, cancel_event, budget_s=20):
    findings = []
    # 1 validate config          0.1s
    # 2 cached status            0.1s  (ServiceCheck + health:results)
    # 3 DNS                      1.0s  (custom hostnames only)
    # 4 TCP                      1.5s
    # 5 TLS                      2.0s  (https only)
    # 6 HTTP HEAD/GET/redirects  8.0s
    # 7 Docker/container         3.0s
    # 8 dependencies             3.0s  (labeled sidecars only)
    # 9 sanitized logs           2.0s  (last 80 lines, redacted)
    # 10 host resources          0.5s  (system:stats cache)
    # 11 compare addresses       0.5s
    # 12 correlate/rank
    # 13 allowed repairs
    # 14 escalation report
```

Skip later steps if budget < step timeout. Record `probe_skipped` evidence.

### E.2 Concurrency, cancellation, locks

- One diagnosis per service: `cache.add("debug:diag:{id}", token, 60)`.
- Parallelize DNS+TCP+cached Docker inspect with a 4-worker pool (same pattern as `fetch_all_widgets` ThreadPoolExecutor, `services.py` 854–856).
- HTTP after TCP success. TLS after TCP if scheme https.
- Cancel: cooperative flag; do not kill in-flight Docker restart (repairs). Diagnosis cancel is safe mid-probe.
- Rate limit: 10 diagnoses / admin / 5 minutes (`debug:rl:{user_id}`).
- Global: max 3 concurrent diagnoses (`debug:diag:global`).

### E.3 Constrained port discovery (no scanning)

Candidate set only:

1. Live Docker HostPorts for this container / slug label.
2. `InstalledService.host_port`.
3. `Service.port`.
4. Catalog `default_port` / parsed compose host hint.
5. **Optional, host-local, permitted:** `psutil.net_connections()` filtered to those candidate ports on `0.0.0.0`/`::`/`services_host` — to answer “is anything listening on the card port?” Not a sweep of 1–65535.

**Forbidden:** nmap, connect to arbitrary ports, user-supplied extra port lists, probing other LAN hosts except the card’s own host.

### E.4 Correlation / ranking

```
score(finding):
    +3 if docker state explains HTTP failure (exited → conn refused)
    +3 if port drift AND TCP succeeds on docker port AND fails on card port
    +2 if sidecar down AND frontend up/down
    +1 if host memory high AND OOMKilled
    -2 if only 401 (reachable)
    -2 if only stale cache
root = highest score; others related[]
```

Do not claim a single root cause when two HIGH findings are independent (e.g. exited **and** stale tunnel). Present “primary” + “also.”

### E.5 Unavailable probes

| Probe down | Finding |
|------------|---------|
| Docker socket | `ISSUE_DOCKER_UNAVAILABLE`; skip 7–8 and port discover |
| Kuma | skip kuma URL compare; HTTP still runs |
| CF API | skip live ingress GET; still compare local `TunnelRoute` |
| psutil in container | use cached `system:stats`; note namespace limits |

---

## F. API and data contracts (PROPOSED)

All routes under dashboard, CSRF + login. Mutations: superuser (pending open question).

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/services/<id>/debug/` | Start diagnosis; 202 + `{incident_id, poll}` |
| `GET` | `/api/services/<id>/debug/<incident_id>/` | Poll diagnosis |
| `POST` | `/api/services/<id>/debug/<incident_id>/repair/` | Start action `{action_id, confirm_token?}` |
| `GET` | `/api/services/<id>/debug/<incident_id>/repair/<job_id>/` | Poll repair |
| `POST` | `/api/services/<id>/debug/<incident_id>/cancel/` | Cancel if state in `{queued,running}` and step cancellable |
| `GET` | `/api/services/<id>/debug/<incident_id>/report.txt` | Download sanitized report |
| `GET` | `/api/services/<id>/debug/<incident_id>/report.json` | Same as copy payload |

### F.1 Examples (no secrets)

Start:

```http
POST /api/services/12/debug/
X-CSRFToken: <token>
```

```json
{
  "incident_id": "dbg_01JEXAMPLE",
  "status": "running",
  "poll_url": "/api/services/12/debug/dbg_01JEXAMPLE/"
}
```

Finding:

```json
{
  "id": "f1",
  "issue_id": "ISSUE_PORT_CARD_DRIFT",
  "severity": "high",
  "confidence": 0.91,
  "title": "The card still opens the old port",
  "plain_language": "Jellyfin is listening on port 8097, but this card still points at 8096.",
  "evidence": [
    {
      "probe_id": "PROBE_DOCKER_PORTS",
      "summary": "Container cc-jellyfin publishes 8097/tcp",
      "data": {"container": "cc-jellyfin", "host_ports": [8097]}
    }
  ],
  "actions": ["ACTION_SYNC_CARD_PORT", "ACTION_RECHECK"]
}
```

Repair:

```json
{
  "action_id": "ACTION_RESTART",
  "risk": "disruptive",
  "confirm_token": "tok_...",
  "confirmation_language": "Restart cc-jellyfin? It will be briefly offline."
}
```

Errors: `403` forbidden; `404` unknown card/incident; `409` lock or stale diagnosis (`{"error":"stale_diagnosis","hint":"Recheck now"}`); `422` action not in latest allowed set; `429` rate limit.

Progress states: `queued` → `running` → `healthy` | `needs_action` | `manual_only` | `failed` | `cancelled`. Repair: `queued` → `running` → `succeeded` | `failed` | `rolled_back`.

### F.2 Persistence

**PROPOSED both:**

- Cache job progress (`debug:inc:{id}` TTL 30 min) for poll.
- Persist `DebugIncident` (new model) for report download / audit: `id`, `service_id`, `created_at`, `actor_id`, `status`, `findings_json` (redacted), `actions_json`, `finished_at`. Retention 14 days; tick prune. Do **not** store raw env, tokens, or `widget_api_key`.

If product wants zero new tables, cache-only is acceptable for v1 but reports vanish on restart (LocMemCache — `base.py` 120–126). **Recommendation:** persist incidents because production cache is process-local and tick/web are different containers.

---

## G. User experience (PROPOSED)

### G.1 Entry

Add one item to `templates/dashboard/_card_menu.html` after “Open in a new tab”:

```html
<button type="button" class="service-card-dropdown__item" data-action="debug" role="menuitem">Debug service</button>
```

Visible to anyone who can open the card. Repair controls inside the modal: superuser only.

### G.2 Modal language (copy)

| State | Heading | Body |
|-------|---------|------|
| Loading | DEBUG | Checking this card… |
| Healthy | LOOKS HEALTHY | Control Center can reach this service. Nothing to fix. |
| One cause | {plain title} | {plain_language} |
| Multiple | SEVERAL PROBLEMS | The most likely cause is first. |
| Port change | PORT CHANGED | Docker is on port {new}. This card still uses {old}. |
| Repair available | | Button: {action label} |
| Repair running | REPAIRING | Reuse update progress track + live log region. |
| Repair ok | REPAIRED | Rechecked: {evidence}. |
| Repair failed | REPAIR FAILED | {plain}. No data was deleted. {rollback note}. |
| Manual only | NEEDS A PERSON | {why}. Copy a report for support. |
| Docker down | DOCKER UNAVAILABLE | Control Center cannot talk to Docker. Managed repairs are hidden. |
| External card | EXTERNAL SERVICE | This card is not a Control Center container. Checks are reachability only. |

Confirmation examples:

- Safe sync: none.
- Restart: existing sentence.
- Recreate: “Recreate the managed container? Named volumes stay. Anything stored only inside the container is lost. Type {name} to continue.”
- Reboot: existing host modal — Debug should deep-link, not invent a second reboot.

### G.3 Visual / a11y

Reuse wood panels (`--tva-wood`, `--tva-orange`), **2px** radii (`theme.css` 161–162, 421), Oswald uppercase titles (`--font-display`), IBM Plex Mono body (`--font-mono`). Orange active/focus outline 2px (`theme.css` 87–88).

Modal: `library-modal` + `update-modal` progress. `role="dialog"` `aria-modal="true"` `aria-labelledby`. Focus first heading/button. Escape closes when idle; Escape during repair asks cancel if cancellable. `aria-live="polite"` on status; `aria-busy` while running. Keyboard: Tab trapped. Mobile: full-width panel like Settings modals.

Copy report: button using settings-tabs clipboard pattern; also download `.txt`.

Do **not** change card grid layout (`apps-cards.js`, dashboard CSS). Tests `DashboardCardTests` / `OverlayViewTests` / `test_apps_cards_compact_layout` must stay green.

### G.4 JS entry

New `static/js/debug-service.js` included from `templates/dashboard/index.html` (admin + members who can open cards). Hook `data-action="debug"` in `card-menu.js` the same way publish calls `ccOpenTunnelPublish`.

---

## H. Security and privacy (PROPOSED + VERIFIED threats)

### H.1 Threat model

| Threat | VERIFIED exposure | Debug control |
|--------|-------------------|---------------|
| Docker socket ≈ root | Socket mounted (`docker-compose.yml` 22) | Allowlist actions + names; no raw exec API |
| SSRF via custom URLs | Health/widget already GET user URLs (`services.py` 139–149, 717–730) | Debug probes same URL only; block `file:`, `gopher:`, link-local metadata (`169.254.169.254`), and non-card hosts |
| DNS rebinding | Custom host DNS | Resolve and require IP in private/LAN or the stored host; do not follow redirect to other hosts |
| Arbitrary port probe | Not present today | Candidate set only (§E.3) |
| Container-name injection | Restart already regex-checked | Keep regex; must match installed/labeled name |
| Unauthorized repairs | Mutations are superuser | Same; CSRF header required ([Django 5.2 CSRF](https://docs.djangoproject.com/en/5.2/howto/csrf/), accessed 2026-09-12) |
| CSRF | Middleware on; AJAX uses `X-CSRFToken` | No `csrf_exempt` |
| Secret leak in reports | Widget keys, vault, CF token, Kuma password, Pi-hole SID | Redact; never echo `widget_api_key`, env passwords, `Authorization` |
| Public CF origin change | Publish already admin | Confirm; never publish new hostnames from Debug |
| Race / duplicate repair | Install uses status row; restart has no lock | Per-service lock |
| Malicious diagnostic content | ServiceCheck.error stored raw | Escape in HTML (`dashboard.js` `escapeHtml` 19–25); report as text |

Host header: Django validates `ALLOWED_HOSTS` via `get_host()` ([Django 5.2 security](https://docs.djangoproject.com/en/5.2/topics/security/), accessed 2026-09-12). `installer._host_from_request` uses `HTTP_X_FORWARDED_HOST` then `get_host()` (`installer.py` 128–134). Debug must not trust forwarded hosts for probe targets.

### H.2 URL / network restrictions

Allow probe if URL host is:

- `Service.host`, or
- `services_host()`, or
- published hostname for that card, or
- Docker bridge IP of **that** container (Kuma-style), or
- hostname parsed from existing `href` / `health_check_url` / `widget_url`.

Deny: other RFC1918 hosts (prevents using Debug as a LAN scanner), cloud metadata IPs, localhost **unless** the card host is already localhost.

### H.3 Redaction

Redact in logs/reports: `password`, `token`, `secret`, `api[_-]?key`, `authorization`, `sid=`, `Bearer `, `FTLCONF_webserver_api_password`, `POSTGRES_PASSWORD`, `MYSQL_`, `APP_KEY`, `TUNNEL_TOKEN`, `cf_api_token`. Replace with `***`. Existing log helper truncates lines to 2048 bytes (`core/logs.py` 117–121) but does **not** redact — Debug must add redaction before display.

### H.4 Safe defaults

- Diagnosis on for all visible cards.
- Repairs off unless superuser.
- Preserve custom URLs default **true**.
- Recreate default **volumes kept**.
- Reboot not in the first action list.

---

## I. Testing strategy (PROPOSED)

Reuse classes in §A.15. Add `dashboard/tests.py` `DebugServiceTests` and `library/tests.py` `PortReconcileTests` / `DetectSyncTests`.

| Area | Cases |
|------|-------|
| Unit probes | TCP fail vs HTTP 401 vs 500; TLS expired mock; Docker paused/exited/missing |
| Port reconcile | managed port change; unmanaged detect refresh; custom URL unchanged; multi-container frontend; multiple bindings → conflict; missing container |
| Propagation | Kuma `edit_monitor` called with new href; CF origin updated; widget cache keys gone; health URL preserved when custom |
| Permissions | member 403 repair; viewer no button; guest 403 start |
| Start/restart/recreate | mock docker; volumes.create already-exists; previous env reused |
| Timeouts/locks | second diagnose 409; cancel; cooldown |
| Redaction | env dump without secrets |
| SSRF | card host A, probe URL host B → rejected |
| Injection | `name: "../../../"` restart 400 |
| UI/a11y | menu item present; Escape; no grid class changes (`test_apps_cards_compact_layout`) |
| Failure injection | patch Docker, `requests`, `socket.getaddrinfo`, `ssl`, `psutil`, `kuma.set_client_factory`, `cf.set_http_session` |

**Do not** add live Docker integration tests that prune volumes.

Browser: exercise Debug on a tracked card, an app card, a misc custom card, a published card, and a down card. Confirm other dashboard sections still poll.

---

## J. Implementation blueprint (PROPOSED)

### Phase 1 — Port / address reconciliation

**Goal:** detect and apply port/host drift without a full UI engine.

| Add | Purpose |
|-----|---------|
| `library/debug_ports.py` | `inspect_live_address`, `diff_addresses`, `apply_address_sync`, `invalidate_service_caches` |
| `library/detect.py` | **import `get_docker_spec`** (bugfix required for detect to run; small and in-scope for Phase 1 because Debug depends on it) |
| Tests in `library/tests.py` | detect + reconcile |

| Modify | How |
|--------|-----|
| `library/detect.py` 54, 132 | Import spec helper |
| Do **not** change `Service.save()` globally | Callers use `update_fields` |
| Optional: `tick.py` | Cache last ports only; no silent card writes |

Deploy: no migration if cache-only. Restart web+tick after detect import fix.

**Rollback:** revert the import + new module. Cards unchanged if apply was never shipped.

### Phase 2 — Read-only diagnosis

| Add | |
|-----|--|
| `dashboard/debug.py` | pipeline, classifiers, redaction |
| `dashboard/models.py` `DebugIncident` + migration | optional but recommended |
| `dashboard/views.py` start/poll/report | |
| `dashboard/urls.py` | routes |
| `templates/dashboard/_debug_modal.html` | |
| `static/js/debug-service.js` | |
| `static/css/dashboard.css` | modal only, 2px radii |
| `_card_menu.html` | Debug item |
| `card-menu.js` | `data-action="debug"` |

No Docker mutations except inspect/logs.

### Phase 3 — Safe one-button repairs

Wire `ACTION_RECHECK`, `ACTION_DISCOVER_PORT`, `ACTION_SYNC_CARD_PORT` (safe subset), `ACTION_CLEAR_CACHES`, `ACTION_RESYNC_KUMA`, `ACTION_REFRESH_HOST` (when host was CC-managed), `ACTION_OPEN_*`.

Audit every apply. Tests for permissions and custom-URL preserve.

### Phase 4 — Disruptive managed repairs with rollback

Start/unpause/restart (reuse `hostops.restart_container`), stack order, reconnect known network, restore restart policy, managed recreate (extract shared “recreate preserving volumes” from install workers — **do not** call `create_dashboard_card` which deletes cards), env regen, tunnel origin repair, retry install.

**Never** call `uninstall(remove_data=True)`.

Rollback: previous env + previous port binding recorded in incident. If recreate fails, leave old volumes; do not delete them.

### Phase 5 — Reporting, hardening, more classifiers

Report download; retention prune on tick; SSRF tests; TLS classifiers; host resource findings; Pi-hole password mismatch; Nextcloud trusted domains; expanded sidecar graph.

### Files to add / modify (checklist)

See JSON `implementation_files`. High level:

**Add:** `docs/research/*` (this PR), later `dashboard/debug.py`, `library/debug_ports.py`, `dashboard/migrations/0009_debugincident.py`, `templates/dashboard/_debug_modal.html`, `static/js/debug-service.js`, tests.

**Modify:** `dashboard/urls.py`, `dashboard/views.py`, `dashboard/models.py` (incident + optional AuditEvent type), `templates/dashboard/_card_menu.html`, `templates/dashboard/index.html` (include modal/js), `static/js/card-menu.js`, `static/css/dashboard.css`, `library/detect.py` (import), `dashboard/management/commands/tick.py` (prune incidents), `core/models.py` if new audit type, `core/logs.py` if Debug needs sidecar names.

**Do not modify:** production card grid CSS layout, `docker-compose.yml` (unless a future phase needs nothing — it does not), catalog compose as a “fix,” install workers’ volume wipe behavior.

### Backward compatibility

- New menu item only.
- New optional model.
- Existing health/Kuma/CF unchanged.
- `Service.save()` behavior unchanged (callers must not start using bare `save()` for sync).

### Deploy / restart

LocMem cache is per-process: web and tick do not share diagnosis locks unless incidents are in SQLite. **Persist incidents** so poll works across gunicorn workers (compose uses `--workers 1` today, but do not rely on it). After Phase 1 detect fix: restart `control-center-tick`.

### Risks

| Risk | Mitigation |
|------|------------|
| `save()` clobbers URLs | `update_fields` + preserve heuristic |
| Recreate without volumes | Reuse `_ensure_volume` names; tests |
| Public tunnel rewrite | Confirm; skip CC targets |
| Detect NameError | Phase 1 import |
| Superuser vs role admin | Open question |
| Widget key in reports | Redaction tests |
| Dashboard layout regression | Do not touch card CSS grid |

---

## Open product questions

See JSON `open_questions`. The decisions that block implementation:

1. Does “admin-only repairs” mean `is_superuser` (current Library/Docker) or `core.access.is_admin` (role)?
2. May tick silently sync unmanaged ports onto cards, or only Debug with a button?
3. Persist `DebugIncident` vs cache-only?
4. If health URL was customized, sync port inside the URL or leave it and only warn?
5. Offer managed recreate from Debug, or only “Open Library → Uninstall/Install”?
6. Should Debug start a stopped Kuma automatically (as `ensure_kuma_installed` already can)?
7. Viewer: diagnosis text or only “ask an admin”?

**Recommendation (labeled, not a fact):** (1) superuser to match existing dangerous APIs; (2) Debug-only apply; (3) persist incidents; (4) rewrite URL only if auto-derived; (5) offer recreate with typed confirm; (6) start existing Kuma, never auto-install; (7) viewers get plain-language + copy report, no probes that hit widget API keys.

---

## External documentation (accessed 2026-09-12)

| Topic | URL | vs repo |
|-------|-----|---------|
| Docker Engine inspect / PortMap / RestartPolicy | https://docs.docker.com/reference/api/engine/ | Repo uses docker-py; fields match `NetworkSettings.Ports`, `HostConfig.RestartPolicy` |
| docker-py containers | https://docker-py.readthedocs.io/en/stable/containers.html | `restart(timeout=)` default 10; repo uses 20 |
| Django 5.2 security / CSRF / Host | https://docs.djangoproject.com/en/5.2/topics/security/ · https://docs.djangoproject.com/en/5.2/howto/csrf/ | Repo: `CsrfViewMiddleware`, `X-CSRFToken`, `ALLOWED_HOSTS`; CSRF cookie Secure in prod |
| Uptime Kuma internal Socket.IO | https://github.com/louislam/uptime-kuma/wiki/Internal-API | Unofficial; repo wraps via uptime-kuma-api |
| uptime-kuma-api | https://uptime-kuma-api.readthedocs.io/en/stable/api.html | `add_monitor` / `edit_monitor` used in `kuma.py` |
| Cloudflare tunnel API | https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel-api/ | Ingress replace + catch-all 404; repo `config_src=cloudflare` |
| psutil | https://psutil.readthedocs.io/latest/api.html | Matches `get_system_stats` |
| Python ssl | https://docs.python.org/3/library/ssl.html | Use `create_default_context`; no verify-off |
| Ubuntu systemctl reboot | https://manpages.ubuntu.com/manpages/xenial/man1/systemctl.1.html | Matches `hostops` fallback |
| Raspberry Pi systemd | https://www.raspberrypi.com/documentation/computers/using_linux.html (systemd) | Host is systemd; reboot is last resort |

**Conflict callout:** Cloudflare’s current docs emphasize Zero Trust “cloudflared configurations” resources; this repo’s `_request` uses `/accounts/{id}/cfd_tunnel/.../configurations`, which the same docs still show in the “Create a tunnel (API)” guide. Implement tunnel origin repair through `library.cloudflare._sync_ingress`, not a new HTTP client.

**Conflict callout:** Official Kuma API is unsupported; Debug must treat wrapper failures as infra, and must not scrape the Kuma UI.

---

## Done-criteria for the implementing agent

1. Every dashboard card type can start Debug.
2. Managed Docker gets Docker + stack + env + recreate options; custom/external get reachability + copy report.
3. A verified port change updates Docker record, card, href, health, widget, Kuma, CF origin, and caches — with custom URL preservation.
4. Safe actions are one click; disruptive confirm; destructive typed confirm.
5. No volume/image/log wipe actions.
6. Superuser (or decided admin) only for repairs; CSRF; redaction; audit.
7. Tests cover reconcile, permissions, SSRF, redaction, and no card-layout CSS churn.
