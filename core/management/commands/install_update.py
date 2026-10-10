from django.core.management.base import BaseCommand, CommandError

from core import updates
from core.models import UpdateStatus


class Command(BaseCommand):
    help = "Apply a GitHub release or commit in place. Used by the in-app updater."

    def add_arguments(self, parser):
        parser.add_argument("tag", help="Release tag or commit sha to install")
        parser.add_argument(
            "--username",
            default="",
            help="Admin username recorded in the audit log.",
        )
        parser.add_argument(
            "--ref-type",
            choices=("tag", "commit"),
            default="tag",
            help="tag installs a release; commit installs a branch tip.",
        )

    def handle(self, *args, **options):
        tag = (options["tag"] or "").strip()
        ref_type = options["ref_type"]
        if ref_type == "commit":
            if not updates.SHA_PATTERN.match(tag.lower()):
                raise CommandError("Invalid commit.")
        elif not updates.TAG_PATTERN.match(tag):
            raise CommandError("Invalid release tag.")
        updates.run_install(tag, options.get("username") or "", ref_type=ref_type)
        status = UpdateStatus.load()
        if status.install_state == UpdateStatus.InstallState.FAILED:
            raise CommandError(status.install_step or "Update failed")
        self.stdout.write(self.style.SUCCESS(f"Installed {tag}"))
