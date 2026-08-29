from django.core.management.base import BaseCommand, CommandError

from core import updates
from core.models import UpdateStatus


class Command(BaseCommand):
    help = "Apply a GitHub release in place. Used by the in-app updater."

    def add_arguments(self, parser):
        parser.add_argument("tag", help="Release tag to install, for example v0.2.1")
        parser.add_argument(
            "--username",
            default="",
            help="Admin username recorded in the audit log.",
        )

    def handle(self, *args, **options):
        tag = (options["tag"] or "").strip()
        if not updates.TAG_PATTERN.match(tag):
            raise CommandError("Invalid release tag.")
        updates.run_install(tag, options.get("username") or "")
        status = UpdateStatus.load()
        if status.install_state == UpdateStatus.InstallState.FAILED:
            raise CommandError(status.install_step or "Update failed")
        self.stdout.write(self.style.SUCCESS(f"Installed {tag}"))
