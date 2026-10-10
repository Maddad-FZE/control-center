import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.themes.registry import SLUG_RE, clear_theme_cache


class Command(BaseCommand):
    help = "Scaffold a theme pack folder."

    def add_arguments(self, parser):
        parser.add_argument("slug")
        parser.add_argument("--extends", default="")
        parser.add_argument("--name", default="")
        parser.add_argument("--dir", default="", help="Pack root. Default: data/themes")

    def handle(self, *args, **options):
        slug = options["slug"].strip().lower()
        if not SLUG_RE.match(slug):
            raise CommandError("Slug must match ^[a-z0-9][a-z0-9-]{1,47}$")
        root = Path(options["dir"]) if options["dir"] else Path(settings.BASE_DIR) / "data" / "themes"
        dest = root / slug
        if dest.exists():
            raise CommandError(f"{dest} already exists")
        extends = options["extends"].strip() or None
        if extends and not SLUG_RE.match(extends):
            raise CommandError("extends is not a valid slug")
        name = options["name"].strip() or slug.replace("-", " ").title()
        dest.mkdir(parents=True)
        (dest / "static").mkdir()
        (dest / "templates").mkdir()
        manifest = {
            "schema": 1,
            "slug": slug,
            "name": name,
            "extends": extends,
            "tokens": {},
            "layout": {
                "chrome": "topbar",
                "pinned": True,
                "show_clock": True,
                "footer": "visible",
            },
            "helper": {"mode": "floating", "dock": "rail"},
            "dashboard": {"arrangement": "board", "stats": "sidebar"},
            "supports_crt": True,
            "assets": {"css": ["skin.css"], "js": []},
        }
        (dest / "theme.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (dest / "static" / "skin.css").write_text(
            "/* Add overrides inside @layer theme so they beat the parent skin. */\n@layer theme {\n}\n",
            encoding="utf-8",
        )
        (dest / "DESIGN.md").write_text(
            f"# {name}\n\nVisual rules for this pack. This file is the authority inside `{dest.name}/`.\n",
            encoding="utf-8",
        )
        clear_theme_cache()
        self.stdout.write(self.style.SUCCESS(f"Created {dest}"))
        self.stdout.write("Run collectstatic and restart to serve new static files.")
