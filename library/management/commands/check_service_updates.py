from django.core.management.base import BaseCommand

from library.versions import check_all


class Command(BaseCommand):
    help = "Check GitHub for latest releases of library catalog services"

    def handle(self, *args, **options):
        check_all()
        self.stdout.write(self.style.SUCCESS("Catalog release check complete."))
