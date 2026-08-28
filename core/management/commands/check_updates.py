from django.core.management.base import BaseCommand

from core import updates
from core.version import get_current_version


class Command(BaseCommand):
    help = "Check GitHub for a newer release and store the result."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Check even if the last check is within the throttle window.",
        )

    def handle(self, *args, **options):
        status = updates.maybe_check_for_update(force=options["force"])
        current = get_current_version()

        if status.check_error:
            self.stdout.write(self.style.WARNING(status.check_error))
            return

        if updates.update_available(status):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Update available: {status.latest_version} (current v{current})"
                )
            )
        else:
            self.stdout.write(f"Up to date (v{current})")
