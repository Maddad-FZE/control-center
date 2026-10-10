from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.themes.registry import clear_theme_cache, get_packs


class Command(BaseCommand):
    help = "Validate installed theme packs."

    def add_arguments(self, parser):
        parser.add_argument("--collect", action="store_true", help="Run collectstatic after a clean check.")

    def handle(self, *args, **options):
        clear_theme_cache()
        packs = get_packs()
        if not packs:
            self.stderr.write("No theme packs found.")
            return
        problems = 0
        for pack in packs.values():
            self.stdout.write(f"{pack.slug}: {pack.name} ({pack.path})")
            if pack.extends and pack.extends not in packs:
                problems += 1
                self.stderr.write(f"  extends missing pack {pack.extends}")
            for asset in pack.assets_css + pack.assets_js:
                if not (pack.static_dir / asset).is_file():
                    problems += 1
                    self.stderr.write(f"  missing asset {asset}")
        if "wood" not in packs:
            problems += 1
            self.stderr.write("wood pack is missing")
        if problems:
            self.stderr.write(self.style.ERROR(f"{problems} problem(s)"))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(f"{len(packs)} theme(s) ok"))
        if options["collect"]:
            call_command("collectstatic", interactive=False, verbosity=0)
