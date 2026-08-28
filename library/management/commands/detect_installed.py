from django.core.management.base import BaseCommand

import docker

from library.detect import sync_detected_services


class Command(BaseCommand):
    help = "Detect Docker containers and match them to library catalog entries."

    def handle(self, *args, **options):
        try:
            result = sync_detected_services()
        except docker.errors.DockerException as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            return
        if result.get("error"):
            self.stderr.write(self.style.ERROR(result["error"]))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Detected {result['detected']} service(s): "
                f"{result['adopted']} adopted, {result['refreshed']} refreshed, "
                f"{result['removed']} removed."
            )
        )
