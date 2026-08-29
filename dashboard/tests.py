from django.test import TestCase
from django.utils import timezone

from dashboard.models import Service, ServiceCategory, ServiceCheck
from dashboard import services


class HealthQueryTests(TestCase):
    def setUp(self):
        self.cat = ServiceCategory.objects.create(name="Test")
        self.svc = Service.objects.create(
            category=self.cat,
            name="Probe",
            href="http://127.0.0.1:9/",
            enabled=True,
        )

    def test_status_map_uses_latest_check(self):
        old = timezone.now() - timezone.timedelta(hours=2)
        ServiceCheck.objects.create(service=self.svc, is_up=False, response_ms=10)
        latest = ServiceCheck.objects.create(service=self.svc, is_up=True, response_ms=4)
        ServiceCheck.objects.filter(pk=latest.pk).update(checked_at=timezone.now())
        ServiceCheck.objects.filter(is_up=False).update(checked_at=old)
        status = services.service_status_map()
        self.assertTrue(status[self.svc.id]["is_up"])
        self.assertEqual(status[self.svc.id]["response_ms"], 4)

    def test_prune_old_checks_keeps_recent(self):
        stale = ServiceCheck.objects.create(service=self.svc, is_up=True, response_ms=1)
        fresh = ServiceCheck.objects.create(service=self.svc, is_up=True, response_ms=2)
        ServiceCheck.objects.filter(pk=stale.pk).update(
            checked_at=timezone.now() - timezone.timedelta(hours=72)
        )
        deleted = services.prune_old_checks()
        self.assertGreaterEqual(deleted, 1)
        self.assertTrue(ServiceCheck.objects.filter(pk=fresh.pk).exists())
        self.assertFalse(ServiceCheck.objects.filter(pk=stale.pk).exists())

    def test_health_from_latest_includes_checked_at(self):
        ServiceCheck.objects.create(service=self.svc, is_up=True, response_ms=8)
        rows = services.health_from_latest_checks()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.svc.id)
        self.assertTrue(rows[0]["checked_at"])
