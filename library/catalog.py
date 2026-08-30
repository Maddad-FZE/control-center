"""Curated addon and service catalog for the app library."""

import re

ADDONS = [
    {
        "slug": "notes",
        "name": "Notes",
        "description": "Personal notes that use the same Control Center login. Keep short lists, reminders, and shared household text in one place.",
        "url_name": "notes:list",
        "url_prefix": "/notes/",
        "category": "Productivity",
        "icon": "note",
        "removable": True,
    },
]

def _compose(name, image, port, container_port=None, volumes=None, env=None):
    cp = container_port or port
    lines = [
        "services:",
        f"  {name}:",
        f"    image: {image}",
        "    restart: unless-stopped",
        "    ports:",
        f"      - \"{port}:{cp}\"",
    ]
    if volumes:
        lines.append("    volumes:")
        for vol in volumes:
            lines.append(f"      - {vol}")
    if env:
        lines.append("    environment:")
        for key, value in env.items():
            lines.append(f"      {key}: \"{value}\"")
    return "\n".join(lines)


SERVICES = [
    # Home Automation
    {
        "slug": "home-assistant",
        "name": "Home Assistant",
        "tagline": "Open-source home automation",
        "category": "Home Automation",
        "repo": "home-assistant/core",
        "website": "https://www.home-assistant.io/",
        "icon": "https://cdn.simpleicons.org/homeassistant",
        "default_port": 8123,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("homeassistant", "ghcr.io/home-assistant/home-assistant:stable", 8123, volumes=["./config:/config", "/etc/localtime:/etc/localtime:ro"]),
    },
    {
        "slug": "esphome",
        "name": "ESPHome",
        "tagline": "Firmware and management for ESP devices",
        "category": "Home Automation",
        "repo": "esphome/esphome",
        "website": "https://esphome.io/",
        "icon": "https://cdn.simpleicons.org/esphome",
        "default_port": 6052,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("esphome", "ghcr.io/esphome/esphome:stable", 6052, volumes=["./config:/config", "/etc/localtime:/etc/localtime:ro"]),
    },
    {
        "slug": "zigbee2mqtt",
        "name": "Zigbee2MQTT",
        "tagline": "Bridge Zigbee devices to MQTT",
        "category": "Home Automation",
        "repo": "Koenkk/zigbee2mqtt",
        "website": "https://www.zigbee2mqtt.io/",
        "icon": "https://cdn.simpleicons.org/zigbee",
        "default_port": 8080,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("zigbee2mqtt", "koenkk/zigbee2mqtt", 8080, volumes=["./data:/app/data", "/run/udev:/run/udev:ro"]),
    },
    {
        "slug": "nodered",
        "name": "Node-RED",
        "tagline": "Flow-based automation for IoT",
        "category": "Home Automation",
        "repo": "node-red/node-red",
        "website": "https://nodered.org/",
        "icon": "https://cdn.simpleicons.org/nodered",
        "default_port": 1880,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("nodered", "nodered/node-red:latest", 1880, volumes=["./data:/data"]),
    },
    {
        "slug": "mosquitto",
        "name": "Mosquitto",
        "tagline": "Lightweight MQTT broker",
        "category": "Home Automation",
        "repo": "eclipse-mosquitto/mosquitto",
        "website": "https://mosquitto.org/",
        "icon": "https://cdn.simpleicons.org/eclipsemosquitto",
        "default_port": 1883,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("mosquitto", "eclipse-mosquitto:2", 1883, volumes=["./config:/mosquitto/config", "./data:/mosquitto/data", "./log:/mosquitto/log"]),
    },
    # Networking
    {
        "slug": "pihole",
        "name": "Pi-hole",
        "tagline": "Network-wide ad blocking DNS",
        "category": "Networking",
        "repo": "pi-hole/pi-hole",
        "website": "https://pi-hole.net/",
        "icon": "https://cdn.simpleicons.org/pihole",
        "default_port": 80,
        "path": "/admin/",
        "widget_type": "pihole",
        "compose": _compose("pihole", "pihole/pihole:latest", 80, env={"TZ": "Asia/Dubai", "FTLCONF_webserver_api_enabled": "true"}),
    },
    {
        "slug": "adguard-home",
        "name": "AdGuard Home",
        "tagline": "DNS ad blocker and parental controls",
        "category": "Networking",
        "repo": "AdguardTeam/AdGuardHome",
        "website": "https://adguard.com/adguard-home.html",
        "icon": "https://cdn.simpleicons.org/adguard",
        "default_port": 3000,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("adguard", "adguard/adguardhome", 3000, volumes=["./work:/opt/adguardhome/work", "./conf:/opt/adguardhome/conf"]),
    },
    {
        "slug": "nginx-proxy-manager",
        "name": "Nginx Proxy Manager",
        "tagline": "Easy reverse proxy with SSL UI",
        "category": "Networking",
        "repo": "NginxProxyManager/nginx-proxy-manager",
        "website": "https://nginxproxymanager.com/",
        "icon": "https://cdn.simpleicons.org/nginx",
        "default_port": 81,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("npm", "jc21/nginx-proxy-manager:latest", 81, volumes=["./data:/data", "./letsencrypt:/etc/letsencrypt"]),
    },
    {
        "slug": "traefik",
        "name": "Traefik",
        "tagline": "Cloud-native edge router",
        "category": "Networking",
        "repo": "traefik/traefik",
        "website": "https://traefik.io/",
        "icon": "https://cdn.simpleicons.org/traefikproxy",
        "default_port": 8080,
        "path": "/dashboard/",
        "widget_type": "none",
        "compose": _compose("traefik", "traefik:v3.0", 8080, volumes=["/var/run/docker.sock:/var/run/docker.sock:ro", "./traefik.yml:/etc/traefik/traefik.yml:ro"]),
    },
    {
        "slug": "wireguard-easy",
        "name": "WireGuard Easy",
        "tagline": "WireGuard VPN with a web UI",
        "category": "Networking",
        "repo": "wg-easy/wg-easy",
        "website": "https://github.com/wg-easy/wg-easy",
        "icon": "https://cdn.simpleicons.org/wireguard",
        "default_port": 51821,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("wg-easy", "ghcr.io/wg-easy/wg-easy", 51821, env={"WG_HOST": "192.168.0.40", "PASSWORD": "changeme"}, volumes=["./data:/etc/wireguard"]),
    },
    {
        "slug": "cloudflare-tunnel",
        "name": "Cloudflare Tunnel",
        "tagline": "Publish services online without opening ports",
        "category": "Networking",
        "repo": "cloudflare/cloudflared",
        "website": "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/",
        "icon": "https://cdn.simpleicons.org/cloudflare",
        "default_port": 0,
        "path": "/",
        "widget_type": "none",
        "compose": (
            "services:\n"
            "  cloudflared:\n"
            "    image: cloudflare/cloudflared:latest\n"
            "    restart: unless-stopped\n"
            "    command: tunnel --no-autoupdate run\n"
        ),
    },
    # Media
    {
        "slug": "jellyfin",
        "name": "Jellyfin",
        "tagline": "Free software media system",
        "category": "Media",
        "repo": "jellyfin/jellyfin",
        "website": "https://jellyfin.org/",
        "icon": "https://cdn.simpleicons.org/jellyfin",
        "default_port": 8096,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("jellyfin", "jellyfin/jellyfin", 8096, volumes=["./config:/config", "./cache:/cache", "./media:/media"]),
    },
    {
        "slug": "immich",
        "name": "Immich",
        "tagline": "Self-hosted photo and video backup",
        "category": "Media",
        "repo": "immich-app/immich",
        "website": "https://immich.app/",
        "icon": "https://cdn.simpleicons.org/immich",
        "default_port": 2283,
        "path": "/",
        "widget_type": "none",
        "compose": "# See https://github.com/immich-app/immich/releases/latest/download/docker-compose.yml",
    },
    {
        "slug": "navidrome",
        "name": "Navidrome",
        "tagline": "Lightweight music server",
        "category": "Media",
        "repo": "navidrome/navidrome",
        "website": "https://www.navidrome.org/",
        "icon": "https://cdn.simpleicons.org/navidrome",
        "default_port": 4533,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("navidrome", "deluan/navidrome:latest", 4533, volumes=["./data:/data", "./music:/music:ro"]),
    },
    {
        "slug": "audiobookshelf",
        "name": "Audiobookshelf",
        "tagline": "Audiobook and podcast server",
        "category": "Media",
        "repo": "advplyr/audiobookshelf",
        "website": "https://www.audiobookshelf.org/",
        "icon": "https://cdn.simpleicons.org/audiobookshelf",
        "default_port": 13378,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("audiobookshelf", "ghcr.io/advplyr/audiobookshelf:latest", 13378, container_port=80, volumes=["./audiobooks:/audiobooks", "./podcasts:/podcasts", "./config:/config"]),
    },
    {
        "slug": "sonarr",
        "name": "Sonarr",
        "tagline": "TV series collection manager",
        "category": "Media",
        "repo": "Sonarr/Sonarr",
        "website": "https://sonarr.tv/",
        "icon": "https://cdn.simpleicons.org/sonarr",
        "default_port": 8989,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("sonarr", "lscr.io/linuxserver/sonarr:latest", 8989, volumes=["./config:/config", "./tv:/tv"]),
    },
    {
        "slug": "radarr",
        "name": "Radarr",
        "tagline": "Movie collection manager",
        "category": "Media",
        "repo": "Radarr/Radarr",
        "website": "https://radarr.video/",
        "icon": "https://cdn.simpleicons.org/radarr",
        "default_port": 7878,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("radarr", "lscr.io/linuxserver/radarr:latest", 7878, volumes=["./config:/config", "./movies:/movies"]),
    },
    {
        "slug": "prowlarr",
        "name": "Prowlarr",
        "tagline": "Indexer manager for *arr apps",
        "category": "Media",
        "repo": "Prowlarr/Prowlarr",
        "website": "https://prowlarr.com/",
        "icon": "https://cdn.simpleicons.org/prowlarr",
        "default_port": 9696,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("prowlarr", "lscr.io/linuxserver/prowlarr:latest", 9696, volumes=["./config:/config"]),
    },
    # Monitoring
    {
        "slug": "uptime-kuma",
        "name": "Uptime Kuma",
        "tagline": "Self-hosted uptime monitoring",
        "category": "Monitoring",
        "repo": "louislam/uptime-kuma",
        "website": "https://uptime.kuma.pet/",
        "icon": "https://cdn.simpleicons.org/uptimekuma",
        "default_port": 3001,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("uptime-kuma", "louislam/uptime-kuma:1", 3001, volumes=["./data:/app/data"]),
    },
    {
        "slug": "grafana",
        "name": "Grafana",
        "tagline": "Metrics dashboards and alerting",
        "category": "Monitoring",
        "repo": "grafana/grafana",
        "website": "https://grafana.com/",
        "icon": "https://cdn.simpleicons.org/grafana",
        "default_port": 3000,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("grafana", "grafana/grafana-oss", 3000, volumes=["./data:/var/lib/grafana"]),
    },
    {
        "slug": "prometheus",
        "name": "Prometheus",
        "tagline": "Metrics collection and storage",
        "category": "Monitoring",
        "repo": "prometheus/prometheus",
        "website": "https://prometheus.io/",
        "icon": "https://cdn.simpleicons.org/prometheus",
        "default_port": 9090,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("prometheus", "prom/prometheus:latest", 9090, volumes=["./prometheus.yml:/etc/prometheus/prometheus.yml", "./data:/prometheus"]),
    },
    {
        "slug": "netdata",
        "name": "Netdata",
        "tagline": "Real-time server monitoring",
        "category": "Monitoring",
        "repo": "netdata/netdata",
        "website": "https://www.netdata.cloud/",
        "icon": "https://cdn.simpleicons.org/netdata",
        "default_port": 19999,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("netdata", "netdata/netdata:stable", 19999, volumes=["netdataconfig:/etc/netdata", "netdatalib:/var/lib/netdata", "netdatacache:/var/cache/netdata"]),
    },
    {
        "slug": "speedtest-tracker",
        "name": "Speedtest Tracker",
        "tagline": "Track internet speed over time",
        "category": "Monitoring",
        "repo": "alexjustesen/speedtest-tracker",
        "website": "https://speedtest-tracker.dev/",
        "icon": "https://cdn.simpleicons.org/speedtest",
        "default_port": 8444,
        "path": "/",
        "widget_type": "speedtest",
        "compose": _compose("speedtest-tracker", "lscr.io/linuxserver/speedtest-tracker:latest", 8444, container_port=80, volumes=["./config:/config"]),
    },
    {
        "slug": "beszel",
        "name": "Beszel",
        "tagline": "Lightweight server monitoring hub",
        "category": "Monitoring",
        "repo": "henrygd/beszel",
        "website": "https://beszel.dev/",
        "icon": "https://cdn.simpleicons.org/linux",
        "default_port": 8090,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("beszel", "henrygd/beszel:latest", 8090, volumes=["./beszel_data:/beszel_data"]),
    },
    # Storage and Files
    {
        "slug": "nextcloud",
        "name": "Nextcloud",
        "tagline": "Self-hosted files and collaboration",
        "category": "Storage and Files",
        "repo": "nextcloud/server",
        "website": "https://nextcloud.com/",
        "icon": "https://cdn.simpleicons.org/nextcloud",
        "default_port": 8080,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("nextcloud", "nextcloud:latest", 8080, container_port=80, volumes=["./nextcloud:/var/www/html"]),
    },
    {
        "slug": "syncthing",
        "name": "Syncthing",
        "tagline": "Continuous file synchronization",
        "category": "Storage and Files",
        "repo": "syncthing/syncthing",
        "website": "https://syncthing.net/",
        "icon": "https://cdn.simpleicons.org/syncthing",
        "default_port": 8384,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("syncthing", "syncthing/syncthing:latest", 8384, volumes=["./config:/var/syncthing/config", "./data:/var/syncthing"]),
    },
    {
        "slug": "paperless-ngx",
        "name": "Paperless-ngx",
        "tagline": "Document management with OCR",
        "category": "Storage and Files",
        "repo": "paperless-ngx/paperless-ngx",
        "website": "https://docs.paperless-ngx.com/",
        "icon": "https://cdn.simpleicons.org/paperlessngx",
        "default_port": 8000,
        "path": "/",
        "widget_type": "none",
        "compose": "# See https://docs.paperless-ngx.com/setup/#docker",
    },
    {
        "slug": "filebrowser",
        "name": "File Browser",
        "tagline": "Web file manager",
        "category": "Storage and Files",
        "repo": "filebrowser/filebrowser",
        "website": "https://filebrowser.org/",
        "icon": "https://cdn.simpleicons.org/files",
        "default_port": 8080,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("filebrowser", "filebrowser/filebrowser:latest", 8080, container_port=80, volumes=["./srv:/srv", "./config:/config"]),
    },
    # Management and Hosting
    {
        "slug": "portainer",
        "name": "Portainer",
        "tagline": "Docker container management UI",
        "category": "Management and Hosting",
        "repo": "portainer/portainer",
        "website": "https://www.portainer.io/",
        "icon": "https://cdn.simpleicons.org/portainer",
        "default_port": 9443,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("portainer", "portainer/portainer-ce:latest", 9443, volumes=["/var/run/docker.sock:/var/run/docker.sock", "./data:/data"]),
    },
    {
        "slug": "dockge",
        "name": "Dockge",
        "tagline": "Compose stack manager",
        "category": "Management and Hosting",
        "repo": "louislam/dockge",
        "website": "https://dockge.kuma.pet/",
        "icon": "https://cdn.simpleicons.org/docker",
        "default_port": 5001,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("dockge", "louislam/dockge:1", 5001, volumes=["/var/run/docker.sock:/var/run/docker.sock", "./data:/app/data", "./stacks:/opt/stacks"]),
    },
    {
        "slug": "coolify",
        "name": "Coolify",
        "tagline": "Self-hosted PaaS for apps and databases",
        "category": "Management and Hosting",
        "repo": "coollabsio/coolify",
        "website": "https://coolify.io/",
        "icon": "https://cdn.simpleicons.org/coolify",
        "default_port": 8000,
        "path": "/",
        "widget_type": "none",
        "compose": "# Install via https://coolify.io/docs/get-started/installation",
    },
    # Security and Auth
    {
        "slug": "vaultwarden",
        "name": "Vaultwarden",
        "tagline": "Bitwarden-compatible password manager",
        "category": "Security and Auth",
        "repo": "dani-garcia/vaultwarden",
        "website": "https://github.com/dani-garcia/vaultwarden",
        "icon": "https://cdn.simpleicons.org/bitwarden",
        "default_port": 8080,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("vaultwarden", "vaultwarden/server:latest", 8080, container_port=80, volumes=["./data:/data"]),
    },
    {
        "slug": "authentik",
        "name": "Authentik",
        "tagline": "Identity provider and SSO",
        "category": "Security and Auth",
        "repo": "goauthentik/authentik",
        "website": "https://goauthentik.io/",
        "icon": "https://cdn.simpleicons.org/authentik",
        "default_port": 9000,
        "path": "/",
        "widget_type": "none",
        "compose": "# See https://docs.goauthentik.io/docs/install-config/install/docker-compose",
    },
    {
        "slug": "authelia",
        "name": "Authelia",
        "tagline": "SSO and 2FA portal",
        "category": "Security and Auth",
        "repo": "authelia/authelia",
        "website": "https://www.authelia.com/",
        "icon": "https://cdn.simpleicons.org/authelia",
        "default_port": 9091,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("authelia", "authelia/authelia:latest", 9091, volumes=["./config:/config"]),
    },
    # Productivity
    {
        "slug": "gitea",
        "name": "Gitea",
        "tagline": "Self-hosted Git service",
        "category": "Productivity",
        "repo": "go-gitea/gitea",
        "website": "https://about.gitea.com/",
        "icon": "https://cdn.simpleicons.org/gitea",
        "default_port": 3000,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("gitea", "gitea/gitea:latest", 3000, volumes=["./data:/data", "/etc/timezone:/etc/timezone:ro", "/etc/localtime:/etc/localtime:ro"]),
    },
    {
        "slug": "n8n",
        "name": "n8n",
        "tagline": "Workflow automation",
        "category": "Productivity",
        "repo": "n8n-io/n8n",
        "website": "https://n8n.io/",
        "icon": "https://cdn.simpleicons.org/n8n",
        "default_port": 5678,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("n8n", "docker.n8n.io/n8nio/n8n", 5678, volumes=["./data:/home/node/.n8n"]),
    },
    {
        "slug": "actual-budget",
        "name": "Actual Budget",
        "tagline": "Local-first personal finance",
        "category": "Productivity",
        "repo": "actualbudget/actual-server",
        "website": "https://actualbudget.com/",
        "icon": "https://cdn.simpleicons.org/actualbudget",
        "default_port": 5006,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("actual-server", "actualbudget/actual-server:latest", 5006, volumes=["./data:/data"]),
    },
    {
        "slug": "mealie",
        "name": "Mealie",
        "tagline": "Recipe manager and meal planner",
        "category": "Productivity",
        "repo": "mealie-recipes/mealie",
        "website": "https://mealie.io/",
        "icon": "https://cdn.simpleicons.org/mealie",
        "default_port": 9925,
        "path": "/",
        "widget_type": "none",
        "compose": _compose("mealie", "ghcr.io/mealie-recipes/mealie:latest", 9925, container_port=9000, volumes=["./data:/app/data"]),
    },
]


def get_service_by_slug(slug):
    for entry in SERVICES:
        if entry["slug"] == slug:
            return entry
    return None


def services_by_category():
    grouped = {}
    for entry in SERVICES:
        grouped.setdefault(entry["category"], []).append(entry)
    return grouped


def service_categories():
    seen = []
    for entry in SERVICES:
        if entry["category"] not in seen:
            seen.append(entry["category"])
    return seen


def get_docker_spec(entry):
    """Return docker install spec, parsing compose when needed."""
    if entry.get("docker"):
        return entry["docker"]

    compose = entry.get("compose", "")
    image = ""
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped.startswith("image:"):
            image = stripped.split("image:", 1)[1].strip()
            break

    host_port_hint = entry.get("default_port", 8080)
    container_port = host_port_hint
    port_match = re.search(r'-\s*"(\d+):(\d+)"', compose)
    if port_match:
        host_port_hint = int(port_match.group(1))
        container_port = int(port_match.group(2))

    volumes = []
    env = {}
    section = None
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped == "volumes:":
            section = "volumes"
            continue
        if stripped == "environment:":
            section = "environment"
            continue
        if stripped.endswith(":") and not stripped.startswith("-"):
            section = None
        if section == "volumes" and stripped.startswith("-"):
            vol = stripped.lstrip("- ").strip().strip('"').strip("'")
            if ":" in vol:
                host_part, container_part = vol.rsplit(":", 1)
                container_path = container_part.split(":")[0]
                if host_part.startswith("/") and not host_part.startswith("./"):
                    continue
                volumes.append(container_path)
        if section == "environment" and ":" in stripped:
            key, _, value = stripped.partition(":")
            env[key.strip()] = value.strip().strip('"').strip("'")

    return {
        "image": image,
        "container_port": container_port,
        "host_port_hint": host_port_hint,
        "volumes": volumes,
        "env": env,
    }


def all_categories():
    categories = []
    for entry in ADDONS:
        if entry["category"] not in categories:
            categories.append(entry["category"])
    for entry in SERVICES:
        if entry["category"] not in categories:
            categories.append(entry["category"])
    return categories


def build_catalog_items(
    addon_enabled_map,
    installed_map,
    release_map,
    app_version="",
    service_cards=None,
):
    """Normalized catalog rows for the unified library grid."""
    from .icons import icon_url_for_entry

    if service_cards is None:
        from dashboard.models import Service

        service_cards = {
            row.catalog_slug: row.id
            for row in Service.objects.exclude(catalog_slug="")
        }
    items = []
    for addon in ADDONS:
        enabled = addon_enabled_map.get(addon["slug"], True)
        items.append(
            {
                "type": "addon",
                "slug": addon["slug"],
                "name": addon["name"],
                "icon": addon.get("icon", ""),
                "icon_url": icon_url_for_entry(addon["slug"], addon.get("icon", "")),
                "description": addon["description"],
                "category": addon["category"],
                "installed": enabled,
                "status": "running" if enabled else "disabled",
                "repo_url": "",
                "version": app_version,
                "url_name": addon.get("url_name", ""),
                "service_id": None,
            }
        )
    for entry in SERVICES:
        inst = installed_map.get(entry["slug"])
        installed = inst is not None and inst.status in (
            "running",
            "stopped",
            "installing",
        )
        status = inst.status if inst else "none"
        service_id = service_cards.get(entry["slug"])
        items.append(
            {
                "type": "service",
                "slug": entry["slug"],
                "name": entry["name"],
                "icon": "",
                "icon_url": icon_url_for_entry(entry["slug"], entry.get("icon", "")),
                "description": LIBRARY_DESCRIPTIONS.get(entry["slug"], entry.get("tagline", "")),
                "category": entry["category"],
                "installed": installed and inst.status != "installing",
                "status": status,
                "managed": inst.managed if inst else True,
                "host_port": inst.host_port if inst else 0,
                "container_name": inst.container_name if inst else "",
                "repo_url": f"https://github.com/{entry['repo']}",
                "version": release_map.get(entry["repo"], ""),
                "url_name": "",
                "service_id": service_id,
            }
        )
    return items


LIBRARY_DESCRIPTIONS = {
    "home-assistant": "Open-source home automation for lights, climate, sensors, and scenes. Talks to hundreds of devices on your LAN so you keep the automations, not a cloud vendor.",
    "esphome": "Build and flash firmware for ESP8266 and ESP32 devices from a browser. Pair with Home Assistant for local sensors, switches, and displays you control.",
    "zigbee2mqtt": "Bridge Zigbee bulbs, locks, and sensors to MQTT without a vendor hub. Exposes every device as a local topic your automations can subscribe to.",
    "nodered": "Drag-and-drop flows that wire IoT devices, APIs, and timers together. Useful for custom automations that sit beside Home Assistant or MQTT.",
    "mosquitto": "A small MQTT broker for device telemetry and command topics. The message bus most homelab automations share.",
    "pihole": "Network-wide DNS ad and tracker blocking for every device on the LAN. Also gives you query logs and optional DHCP on the same box.",
    "adguard-home": "DNS-level ad blocking plus parental controls and per-client rules. A full-featured alternative to Pi-hole with a modern web UI.",
    "nginx-proxy-manager": "Point hostnames at containers and issue Let’s Encrypt certificates from a form. Reverse proxy without hand-editing nginx configs.",
    "traefik": "Cloud-native edge router that discovers Docker services and routes HTTPS to them. Labels on a container become live routes.",
    "wireguard-easy": "WireGuard VPN with a simple web UI for peers and configs. Reach the homelab from phones and laptops without exposing every port.",
    "cloudflare-tunnel": "Cloudflare connector for this host. Link your account in Settings, then publish a service only when you choose to put it on the public internet. Control Center stays on the LAN.",
    "jellyfin": "Free software media server for movies, TV, and music. Streams to browsers, apps, and TVs with no license fee or tracking.",
    "immich": "Self-hosted photo and video backup with mobile upload and a timeline. A private stand-in for Google Photos on your own disk.",
    "navidrome": "Lightweight Subsonic-compatible music server for a local library. Streams to web and mobile clients with a small memory footprint.",
    "audiobookshelf": "Audiobook and podcast server with progress sync across devices. Keeps libraries, series, and listening position on the LAN.",
    "sonarr": "Watches RSS and indexers to collect TV series into your library. Pairs with download clients and Prowlarr for a full *arr stack.",
    "radarr": "Movie collection manager that finds, grabs, and organizes films. Same workflow as Sonarr, aimed at a movie library.",
    "prowlarr": "One indexer manager for Sonarr, Radarr, and the rest of the *arr apps. Add indexers once and share them across the stack.",
    "uptime-kuma": "Self-hosted uptime checks with a status page and alerts. Watch HTTP, ping, and Docker targets from one dashboard.",
    "grafana": "Build metrics dashboards and alert rules on top of Prometheus or other stores. The usual front end for homelab graphs.",
    "prometheus": "Pulls and stores time-series metrics from exporters. The scrape-and-query backend Grafana panels usually read.",
    "netdata": "Real-time per-second charts for CPU, disks, network, and containers. Fast health view of a single host without a big stack.",
    "speedtest-tracker": "Runs scheduled internet speed tests and keeps a history. Shows download, upload, and ping trends on the dashboard widget.",
    "beszel": "Lightweight hub for server and container stats across hosts. Smaller footprint than a full Prometheus stack when you just need basics.",
    "nextcloud": "Self-hosted files, calendars, and collaboration in the browser. Dropbox-style sync that stays on your disks.",
    "syncthing": "Continuous peer-to-peer file sync with no central server. Folders stay in lockstep across PCs, NAS, and phones.",
    "paperless-ngx": "Scan, OCR, and archive documents into a searchable library. Tags, correspondents, and full-text search for household paper.",
    "filebrowser": "Web file manager for a directory on the host. Upload, download, and share files without standing up a full cloud suite.",
    "portainer": "Web UI for Docker containers, images, volumes, and stacks. Day-to-day container chores without living in the CLI.",
    "dockge": "Compose-stack manager with a clean editor and logs. Aimed at people who keep services as docker-compose.yml files.",
    "coolify": "Self-hosted PaaS for apps, databases, and deploys. Push a repo or a compose file and get HTTPS and restarts handled.",
    "vaultwarden": "Unofficial Bitwarden-compatible password manager. Official apps and browser extensions talk to your own server.",
    "authentik": "Identity provider with SSO, applications, and policies. Front the homelab with one login instead of a password per service.",
    "authelia": "SSO and 2FA portal that sits in front of reverse-proxied apps. Lightweight companion to Nginx Proxy Manager or Traefik.",
    "gitea": "Self-hosted Git with issues, PRs, and a web UI. A small GitHub stand-in for private repos on the LAN.",
    "n8n": "Workflow automation that connects APIs, webhooks, and schedules. Build integrations without writing a service for each one.",
    "actual-budget": "Local-first envelope budgeting that syncs through your own server. Money data stays on disk, not at a bank-adjacent SaaS.",
    "mealie": "Recipe manager and meal planner with import from the web. Shopping lists and household recipes in one place.",
}
