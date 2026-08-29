"""Run background maintenance: health pings, prune, GitHub checks, library detect."""

from django.core.management.base import BaseCommand

from core import updates
from dashboard import services
from library.detect import maybe_sync_detected
from library.versions import maybe_check_daily


class Command(BaseCommand):
    help = "Cheap periodic maintenance for health, updates, catalog versions, and detect."

    def handle(self, *args, **options):
        if updates.recover_stale_install():
            self.stdout.write(self.style.WARNING("Cleared a stale in-app update"))

        health = services.maybe_run_health_tick()
        self.stdout.write(f"Health: {len(health)} services")

        pruned = services.prune_old_checks()
        if pruned:
            self.stdout.write(f"Pruned {pruned} old health checks")

        status = updates.maybe_check_for_update()
        if status.check_error:
            self.stdout.write(self.style.WARNING(f"App update check: {status.check_error}"))
        elif status.latest_version:
            self.stdout.write(f"App release: {status.latest_version}")

        maybe_check_daily(background=False)
        detected = maybe_sync_detected()
        if detected and not detected.get("error"):
            self.stdout.write(
                f"Detect: {detected.get('detected', 0)} "
                f"(+{detected.get('adopted', 0)} / ~{detected.get('refreshed', 0)})"
            )
