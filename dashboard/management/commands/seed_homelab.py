from django.core.management.base import BaseCommand

from dashboard.models import Service, ServiceCategory


DEFAULT_DATA = {
    "Network Infrastructure": [
        {
            "name": "Pi-hole",
            "description": "Network DNS Guard",
            "href": "http://192.168.0.40:8888/admin/",
            "icon": "https://cdn.simpleicons.org/pihole/E87722",
            "health_check_url": "http://192.168.0.40:8888/admin/",
            "is_public": False,
            "widget_type": "pihole",
            "widget_url": "http://192.168.0.40:8888",
        },
        {
            "name": "Speedtest",
            "description": "Network Bandwidth Log",
            "href": "http://192.168.0.40:8444/",
            "icon": "https://api.iconify.design/mdi/speedometer.svg?color=%23e87722",
            "health_check_url": "http://192.168.0.40:8444/",
            "widget_type": "speedtest",
            "widget_url": "http://192.168.0.40:8444",
        },
        {
            "name": "Router",
            "description": "BE9300 Router Setup",
            "href": "http://192.168.0.1/",
            "icon": "https://cdn.simpleicons.org/tplink/E87722",
        },
        {
            "name": "Uptime Kuma",
            "description": "Service monitoring",
            "href": "http://192.168.0.40:3001/",
            "icon": "https://api.iconify.design/mdi/heart-pulse.svg?color=%23e87722",
            "health_check_url": "http://192.168.0.40:3001/",
            "catalog_slug": "uptime-kuma",
            "is_misc": False,
        },
    ],
    "Media": [
        {
            "name": "Nuvio",
            "description": "Media streaming",
            "href": "https://nuvio.thezaidan.family/",
            "icon": "https://cdn.simpleicons.org/stremio/E87722",
            "is_public": True,
        },
        {
            "name": "Kavita",
            "description": "Ebook library",
            "href": "https://books.thezaidan.family/",
            "icon": "https://cdn.simpleicons.org/kavita/E87722",
            "is_public": True,
        },
    ],
    "Tools": [
        {
            "name": "Stirling PDF",
            "description": "Private PDF Web Toolkit",
            "href": "http://192.168.0.40:8080/",
            "icon": "https://api.iconify.design/mdi/file-pdf-box.svg?color=%23e87722",
            "health_check_url": "http://192.168.0.40:8080/",
        },
        {
            "name": "n8n",
            "description": "Workflow Automation",
            "href": "https://n8n.thezaidan.family/",
            "icon": "https://cdn.simpleicons.org/n8n/E87722",
            "is_public": True,
        },
        {
            "name": "File Share",
            "description": "Secure file sharing (legacy app)",
            "href": "https://share.thezaidan.family/",
            "icon": "https://api.iconify.design/mdi/share-variant.svg?color=%23e87722",
            "is_public": True,
        },
        {
            "name": "URL Drop",
            "description": "Download to library (legacy app)",
            "href": "http://192.168.0.40:8092/",
            "icon": "https://api.iconify.design/mdi/download.svg?color=%23e87722",
        },
        {
            "name": "Odysseus",
            "description": "AI workspace",
            "href": "https://ai.thezaidan.family/",
            "icon": "https://api.iconify.design/mdi/robot.svg?color=%23e87722",
            "is_public": True,
        },
        {
            "name": "Accounts",
            "description": "Legacy auth admin (retire after cutover)",
            "href": "http://192.168.0.40:8097/",
            "icon": "https://api.iconify.design/mdi/account-cog.svg?color=%23e87722",
        },
    ],
}

BOOKMARKS = [
    {"name": "URL Drop", "href": "http://192.168.0.40:8092/", "icon": "https://api.iconify.design/mdi/download.svg?color=%23e87722"},
    {"name": "CSS Wizard", "href": "http://192.168.0.40:5556/", "icon": "https://api.iconify.design/mdi/palette-swatch-variant.svg?color=%23e87722"},
    {"name": "ntfy", "href": "https://ntfy.thezaidan.family/", "icon": "https://cdn.simpleicons.org/ntfy/E87722"},
    {"name": "Pi Connect", "href": "https://connect.raspberrypi.com/devices", "icon": "https://cdn.simpleicons.org/raspberrypi/E87722"},
    {"name": "AIOMetadata", "href": "https://aiometadata.thezaidan.family/", "icon": "https://api.iconify.design/mdi/database.svg?color=%23e87722"},
    {"name": "AIOStreams", "href": "https://aiostreams.thezaidan.family/stremio/configure", "icon": "https://api.iconify.design/mdi/television-play.svg?color=%23e87722"},
]


class Command(BaseCommand):
    help = "Seed dashboard services from homelab defaults"

    def add_arguments(self, parser):
        parser.add_argument("--yaml", type=str, help="Optional Homepage services.yaml to import")

    def handle(self, *args, **options):
        yaml_path = options.get("yaml")
        if yaml_path:
            self._import_yaml(yaml_path)
        else:
            self._seed_defaults()
        self.stdout.write(self.style.SUCCESS("Seed complete"))

    def _seed_defaults(self):
        for idx, (cat_name, services) in enumerate(DEFAULT_DATA.items()):
            layout = (
                ServiceCategory.Layout.ROWS
                if cat_name == "Network Infrastructure"
                else ServiceCategory.Layout.GRID
            )
            cat, _ = ServiceCategory.objects.get_or_create(
                name=cat_name,
                defaults={"sort_order": idx, "layout": layout},
            )
            if cat.layout != layout or cat.sort_order != idx:
                cat.layout = layout
                cat.sort_order = idx
                cat.save(update_fields=["layout", "sort_order"])
            for sidx, svc in enumerate(services):
                Service.objects.update_or_create(
                    category=cat,
                    name=svc["name"],
                    defaults={
                        "description": svc.get("description", ""),
                        "href": svc["href"],
                        "icon": svc.get("icon", ""),
                        "health_check_url": svc.get("health_check_url", ""),
                        "is_public": svc.get("is_public", False),
                        "sort_order": sidx,
                        "enabled": True,
                        "widget_type": svc.get("widget_type", "none"),
                        "widget_url": svc.get("widget_url", ""),
                        "widget_api_key": svc.get("widget_api_key", ""),
                        "catalog_slug": svc.get("catalog_slug", ""),
                        "is_misc": svc.get("is_misc", False),
                    },
                )
        tools, _ = ServiceCategory.objects.get_or_create(
            name="Tools",
            defaults={"sort_order": 2, "layout": ServiceCategory.Layout.GRID},
        )
        existing = {name.lower() for name in Service.objects.values_list("name", flat=True)}
        for idx, bm in enumerate(BOOKMARKS):
            if bm["name"].lower() in existing:
                continue
            Service.objects.update_or_create(
                category=tools,
                name=bm["name"],
                defaults={
                    "href": bm["href"],
                    "icon": bm.get("icon", ""),
                    "health_check_url": bm["href"],
                    "is_misc": True,
                    "sort_order": 100 + idx,
                    "enabled": True,
                },
            )

    def _import_yaml(self, path):
        import yaml

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for idx, group in enumerate(data or []):
            if not isinstance(group, dict):
                continue
            for cat_name, services in group.items():
                cat, _ = ServiceCategory.objects.get_or_create(
                    name=cat_name, defaults={"sort_order": idx}
                )
                if not isinstance(services, list):
                    continue
                for sidx, item in enumerate(services):
                    if not isinstance(item, dict):
                        continue
                    name, payload = next(iter(item.items()))
                    Service.objects.update_or_create(
                        category=cat,
                        name=name,
                        defaults={
                            "description": payload.get("description", ""),
                            "href": payload.get("href", ""),
                            "icon": payload.get("icon", ""),
                            "health_check_url": payload.get("href", ""),
                            "sort_order": sidx,
                            "enabled": True,
                        },
                    )
