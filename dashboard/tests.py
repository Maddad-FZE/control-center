from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import SiteSettings
from dashboard.models import Service, ServiceCategory, ServiceCheck
from dashboard import kuma, prefs, services
from library.models import InstalledService


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


class OverlayViewTests(TestCase):
    def setUp(self):
        self.cat = ServiceCategory.objects.create(name="Apps")
        self.public = Service.objects.create(
            category=self.cat,
            name="Public App",
            href="http://192.168.0.40:8082/",
            enabled=True,
            is_public=True,
        )
        self.private = Service.objects.create(
            category=self.cat,
            name="Private App",
            href="http://192.168.0.40:8096/",
            enabled=True,
            is_public=False,
        )
        self.admin = User.objects.create_user("admin", password="x", is_superuser=True)
        self.user = User.objects.create_user("member", password="x")

    def test_guest_can_open_public_overlay(self):
        resp = self.client.get(reverse("service_view", args=[self.public.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Open in a new tab")
        self.assertContains(resp, self.public.href)

    def test_guest_cannot_open_private_overlay(self):
        resp = self.client.get(reverse("service_view", args=[self.private.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("dashboard"))

    def test_signed_in_can_open_private_overlay(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("service_view", args=[self.private.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Private App")

    def test_dashboard_links_to_overlay_by_default(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, reverse("service_view", args=[self.public.id]))
        self.assertContains(resp, "Open in overlay")

    def test_always_new_tab_changes_card_href(self):
        prefs.set_open_in_new_tab(self.admin, self.public.id, True)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, f'href="{self.public.href}"')
        self.assertNotContains(
            resp,
            f'class="service-card service-card--app" href="{reverse("service_view", args=[self.public.id])}"',
        )

    def test_open_pref_api_persists(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("api_service_open_pref", args=[self.public.id]),
            data='{"open_in_new_tab": true}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertTrue(prefs.prefers_new_tab(self.user, self.public.id))

    def test_always_open_button_opens_tab(self):
        source = Path(__file__).resolve().parents[1] / "static" / "js" / "service-open.js"
        text = source.read_text(encoding="utf-8")
        self.assertIn('window.open(href, "_blank", "noopener")', text)
        self.assertIn("setPrefRemote", text)

    def test_publish_online_uses_popup_modal(self):
        from core.models import SiteSettings

        site = SiteSettings.load()
        site.cf_api_token = "token"
        site.cf_tunnel_id = "tun"
        site.cf_tunnel_token = "tt"
        site.save()
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, 'id="tunnel-publish-modal"')
        self.assertContains(resp, 'class="library-modal"')
        self.assertContains(resp, "Publish online")
        self.assertContains(resp, 'id="tunnel-publish-subdomain"')
        self.assertContains(resp, 'id="tunnel-publish-zone"')
        css = (Path(__file__).resolve().parents[1] / "static" / "css" / "theme.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".library-modal {", css)
        self.assertIn("position: fixed", css)

    def test_published_card_opens_public_url_and_keeps_lan_menu(self):
        from library.models import TunnelRoute

        TunnelRoute.objects.create(
            hostname="photos.example.com",
            catalog_slug="immich",
            service_id=self.public.id,
            origin_url="http://192.168.0.40:8082",
        )
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "https://photos.example.com/")
        self.assertContains(resp, "Open using IP")
        self.assertContains(resp, f'href="{self.public.href}"')
        overlay = self.client.get(reverse("service_view", args=[self.public.id]))
        self.assertContains(overlay, 'src="https://photos.example.com/"')
        self.assertContains(overlay, "Open using IP")
        self.assertContains(overlay, self.public.href)

    def test_guest_published_card_uses_public_url(self):
        from library.models import TunnelRoute

        TunnelRoute.objects.create(
            hostname="photos.example.com",
            service_id=self.public.id,
            origin_url="http://192.168.0.40:8082",
        )
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "https://photos.example.com/")
        self.assertContains(resp, "Open using IP")

    def test_guest_pref_api_is_rejected(self):
        resp = self.client.post(
            reverse("api_service_open_pref", args=[self.public.id]),
            data='{"open_in_new_tab": true}',
            content_type="application/json",
        )
        self.assertIn(resp.status_code, (302, 403))


class FakeKuma:
    def __init__(self):
        self.monitors = []
        self.heartbeats = {}
        self.next_id = 1
        self.setup_needed = True
        self.setup_calls = []
        self.add_calls = []
        self.edit_calls = []

    def need_setup(self):
        return self.setup_needed

    def setup(self, username, password):
        self.setup_needed = False
        self.setup_calls.append((username, password))
        return {"msg": "Added Successfully."}

    def login(self, username, password):
        return {"ok": True}

    def get_monitors(self):
        return list(self.monitors)

    def add_monitor(self, **kwargs):
        mid = self.next_id
        self.next_id += 1
        self.monitors.append(
            {
                "id": mid,
                "monitorID": mid,
                "name": kwargs.get("name"),
                "url": kwargs.get("url"),
                "interval": kwargs.get("interval"),
            }
        )
        self.add_calls.append(kwargs)
        return {"monitorID": mid}

    def edit_monitor(self, id_, **kwargs):
        self.edit_calls.append((id_, kwargs))
        for monitor in self.monitors:
            if monitor["id"] == id_:
                monitor.update(kwargs)
        return {"monitorID": id_}

    def get_heartbeats(self):
        return self.heartbeats

    def delete_monitor(self, id_):
        self.monitors = [m for m in self.monitors if m["id"] != id_]
        self.heartbeats.pop(id_, None)
        return {"msg": "Deleted Successfully."}

    def disconnect(self):
        pass


class KumaHealthTests(TestCase):
    def setUp(self):
        self.cat = ServiceCategory.objects.create(name="Apps")
        self.cloud = Service.objects.create(
            category=self.cat,
            name="Nextcloud",
            href="http://192.168.0.40:8080/",
            enabled=True,
        )
        Service.objects.filter(pk=self.cloud.pk).update(
            href="http://192.168.0.40:8080/",
            health_check_url="http://192.168.0.40:8080/admin/",
        )
        self.cloud.refresh_from_db()
        self.kuma_card = Service.objects.create(
            category=self.cat,
            name="Uptime Kuma",
            href="http://192.168.0.40:3001/",
            catalog_slug="uptime-kuma",
            is_misc=False,
            enabled=True,
        )
        InstalledService.objects.create(
            slug="uptime-kuma",
            container_name="cc-uptime-kuma",
            host_port=3001,
            status=InstalledService.Status.RUNNING,
        )
        site = SiteSettings.load()
        site.kuma_username = "cc-admin"
        site.kuma_password = "secret"
        site.save()
        self.fake = FakeKuma()
        kuma.set_client_factory(lambda url: self.fake)
        cache.clear()

    def tearDown(self):
        kuma.set_client_factory(None)

    def test_sync_monitors_uses_href_and_skips_kuma_card(self):
        api = kuma.connect_kuma("http://192.168.0.40:3001")
        kuma.sync_monitors(api)
        self.cloud.refresh_from_db()
        self.assertEqual(len(self.fake.add_calls), 1)
        self.assertEqual(self.fake.add_calls[0]["url"], "http://192.168.0.40:8080/")
        self.assertNotEqual(
            self.fake.add_calls[0]["url"], self.cloud.health_check_url
        )
        self.assertEqual(self.cloud.kuma_monitor_id, 1)
        self.kuma_card.refresh_from_db()
        self.assertIsNone(self.kuma_card.kuma_monitor_id)

    @patch("dashboard.services._check_url")
    def test_health_pulls_kuma_not_http_ping(self, ping):
        self.fake.setup_needed = False
        self.fake.monitors = [
            {"id": 7, "monitorID": 7, "name": "Nextcloud", "url": self.cloud.href}
        ]
        self.fake.heartbeats = {
            7: [{"status": 1, "ping": 12.4, "msg": ""}],
        }
        Service.objects.filter(pk=self.cloud.pk).update(kuma_monitor_id=7)
        self.cloud.refresh_from_db()
        results = services.run_health_checks()
        ping.assert_not_called()
        self.assertTrue(ServiceCheck.objects.filter(service=self.cloud, is_up=True).exists())
        self.assertTrue(any(row["id"] == self.cloud.id and row["is_up"] for row in results))

    def test_ensure_does_not_create_or_retag_card(self):
        InstalledService.objects.filter(slug="uptime-kuma").delete()
        Service.objects.filter(pk=self.kuma_card.pk).update(
            catalog_slug="", is_misc=True
        )
        kuma.ensure_kuma_installed()
        self.kuma_card.refresh_from_db()
        self.assertTrue(self.kuma_card.is_misc)
        self.assertEqual(self.kuma_card.catalog_slug, "")
        self.assertFalse(Service.objects.filter(catalog_slug="uptime-kuma").exists())

    def test_delete_card_removes_kuma_monitor(self):
        self.fake.setup_needed = False
        self.fake.monitors = [
            {"id": 7, "monitorID": 7, "name": "Nextcloud", "url": self.cloud.href}
        ]
        Service.objects.filter(pk=self.cloud.pk).update(kuma_monitor_id=7)
        self.cloud.refresh_from_db()
        admin = User.objects.create_user("admin", password="x", is_superuser=True)
        self.client.force_login(admin)
        resp = self.client.post(reverse("api_service_delete", args=[self.cloud.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.fake.monitors, [])
        self.assertFalse(Service.objects.filter(pk=self.cloud.pk).exists())

    def test_dashboard_opens_kuma_in_new_tab(self):
        admin = User.objects.create_user("admin", password="x", is_superuser=True)
        self.client.force_login(admin)
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "Uptime Kuma")
        self.assertContains(resp, f'href="{self.kuma_card.href}"')
        self.assertContains(resp, 'target="_blank"')

    @patch("library.installer.start_install")
    def test_missing_kuma_does_not_raise(self, start):
        InstalledService.objects.filter(slug="uptime-kuma").delete()
        self.assertIsNone(kuma.pull_status())
        start.assert_not_called()

    @patch("library.installer.start_install")
    def test_ensure_does_not_install_when_missing(self, start):
        InstalledService.objects.filter(slug="uptime-kuma").delete()
        self.assertIsNone(kuma.ensure_kuma_installed())
        start.assert_not_called()
        self.assertFalse(InstalledService.objects.filter(slug="uptime-kuma").exists())

    def test_uptime_payload_empty_when_kuma_missing(self):
        InstalledService.objects.filter(slug="uptime-kuma").delete()
        cache.clear()
        self.assertFalse(kuma.kuma_is_running())
        payload = services.get_cached_uptime_payload()
        self.assertFalse(payload["kuma_available"])
        self.assertEqual(payload["uptime"], {})

    @patch("dashboard.services.maybe_run_health_tick")
    def test_uptime_payload_waiting_while_kuma_installing(self, tick):
        InstalledService.objects.filter(slug="uptime-kuma").update(
            status=InstalledService.Status.INSTALLING,
            host_port=0,
        )
        cache.set(
            "uptime:payload",
            {"uptime": {}, "kuma_available": False, "kuma_synced": False},
        )
        payload = services.get_cached_uptime_payload()
        tick.assert_not_called()
        self.assertTrue(payload["kuma_available"])
        self.assertFalse(payload["kuma_synced"])
        self.assertEqual(payload["uptime"], {})

    @patch("dashboard.services.maybe_run_health_tick")
    def test_uptime_payload_empty_until_monitors_exist(self, tick):
        payload = services.get_cached_uptime_payload()
        tick.assert_called_once()
        self.assertTrue(payload["kuma_available"])
        self.assertFalse(payload["kuma_synced"])
        self.assertEqual(payload["uptime"], {})

    def test_uptime_payload_syncs_when_kuma_has_no_monitors(self):
        cache.clear()
        self.fake.setup_needed = False
        payload = services.get_cached_uptime_payload()
        self.cloud.refresh_from_db()
        self.assertEqual(self.cloud.kuma_monitor_id, 1)
        self.assertTrue(payload["kuma_available"])
        self.assertTrue(payload["kuma_synced"])
        self.assertIn(str(self.cloud.id), payload["uptime"])

    @patch("dashboard.kuma.secrets.token_urlsafe", return_value="generated-token")
    def test_kuma_setup_generates_admin(self, _token):
        SiteSettings.objects.filter(pk=1).update(
            kuma_username="", kuma_password="", kuma_setup_done=False
        )
        kuma.connect_kuma("http://192.168.0.40:3001")
        self.assertEqual(self.fake.setup_calls, [("cc-monitor", "generated-token")])
        site = SiteSettings.load()
        self.assertEqual(site.kuma_username, "cc-monitor")
        self.assertEqual(site.kuma_password, "generated-token")

    def test_login_does_not_store_kuma_credentials(self):
        User.objects.create_user("boss", password="pw12345", is_superuser=True)
        SiteSettings.objects.filter(pk=1).update(kuma_username="", kuma_password="")
        self.client.post(reverse("login"), {"username": "boss", "password": "pw12345"})
        site = SiteSettings.load()
        self.assertEqual(site.kuma_username, "")
        self.assertEqual(site.kuma_password, "")

    def test_connect_without_creds_when_kuma_already_setup(self):
        self.fake.setup_needed = False
        SiteSettings.objects.filter(pk=1).update(kuma_username="", kuma_password="")
        self.assertIsNone(kuma.connect_kuma("http://192.168.0.40:3001"))

    def test_uptime_panel_copy(self):
        source = Path(__file__).resolve().parents[1] / "static" / "js" / "dashboard.js"
        text = source.read_text(encoding="utf-8")
        self.assertIn("Install Uptime Kuma to see the monitor.", text)
        self.assertIn("/library/?q=uptime-kuma", text)
        self.assertIn("Waiting for the first monitor check.", text)
        self.assertNotIn("save that login under Settings", text)
        self.assertNotIn("No uptime data yet. Health checks populate history.", text)

    def test_dashboard_renames_monitor_panel(self):
        admin = User.objects.create_user("admin", password="x", is_superuser=True)
        self.client.force_login(admin)
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, ">Monitor</span>")
        self.assertNotContains(resp, "Uptime (24h)")
        self.assertContains(resp, 'data-can-install="1"')

    def test_member_monitor_has_no_install_attr(self):
        member = User.objects.create_user("member", password="x")
        self.client.force_login(member)
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, ">Monitor</span>")
        self.assertNotContains(resp, 'data-can-install="1"')

    def test_settings_monitor_has_show_and_copy(self):
        admin = User.objects.create_user("admin", password="x", is_superuser=True)
        self.client.force_login(admin)
        resp = self.client.get(reverse("settings") + "?section=site")
        self.assertContains(resp, ">Monitor</h3>")
        self.assertContains(resp, "Generated for Uptime Kuma")
        self.assertContains(resp, "data-secret-toggle")
        self.assertContains(resp, "data-secret-copy")
        self.assertContains(resp, ">Show</button>")
        self.assertContains(resp, ">Copy</button>")
        tabs = Path(__file__).resolve().parents[1] / "static" / "js" / "settings-tabs.js"
        js = tabs.read_text(encoding="utf-8")
        self.assertIn("navigator.clipboard.writeText", js)
        self.assertIn("data-secret-toggle", js)


class WizardBubbleAvailabilityTests(TestCase):
    def test_tips_require_a_visible_target(self):
        from pathlib import Path

        source = Path(__file__).resolve().parents[1] / "static" / "js" / "wizard.js"
        text = source.read_text(encoding="utf-8")
        self.assertIn("availableActions", text)
        self.assertIn('id: "tips"', text)
        self.assertIn("tip.target && resolveTarget(tip.target)", text)
        self.assertIn('id: "alerts"', text)
        self.assertIn('id: "update"', text)
        self.assertIn('const common = ["Blink", "Blink", "Pleased", "Wave"];', text)
        self.assertNotIn("setTimeout(done, 2400)", text)
        self.assertIn("function bumpAnim()", text)
        self.assertIn("innerWidth + 24", text)
        self.assertIn('pick(["Show", "GetAttention", "Surprised", "Congratulate"])', text)
        self.assertIn("if (!greeted)", text)
        self.assertIn("cc-wizard--teleport", text)
        self.assertIn('agent._el.style.visibility = "hidden"', text)


class HostOpsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin", password="x", is_superuser=True)
        self.member = User.objects.create_user("member", password="x")

    def test_admin_dashboard_has_reboot_and_usb(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "Restart Pi")
        self.assertContains(resp, 'data-panel-id="usb"')
        self.assertContains(resp, 'data-admin="1"')

    def test_member_dashboard_hides_reboot(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse("dashboard"))
        self.assertNotContains(resp, "Restart Pi")
        self.assertContains(resp, 'data-panel-id="usb"')
        self.assertNotContains(resp, 'data-admin="1"')

    def test_reboot_forbidden_for_member(self):
        self.client.force_login(self.member)
        resp = self.client.post(reverse("api_system_reboot"))
        self.assertEqual(resp.status_code, 403)

    def test_reboot_schedules_for_admin(self):
        self.client.force_login(self.admin)
        with patch("dashboard.hostops.threading.Timer") as timer:
            timer.return_value.start = MagicMock()
            resp = self.client.post(reverse("api_system_reboot"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        timer.assert_called()

    def test_docker_restart_rejects_bad_name(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("api_docker_restart"),
            data='{"name":"../evil"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_docker_restart_calls_container(self):
        self.client.force_login(self.admin)
        fake_container = MagicMock()
        fake_client = MagicMock()
        fake_client.containers.get.return_value = fake_container
        with patch("dashboard.hostops._docker_client", return_value=fake_client):
            resp = self.client.post(
                reverse("api_docker_restart"),
                data='{"name":"cc-pihole"}',
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        fake_container.restart.assert_called_once()

    def test_usb_list_reads_sysfs(self):
        import tempfile
        from pathlib import Path

        from dashboard import hostops

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "devices"
            dev = root / "1-1"
            iface = dev / "1-1:1.0"
            iface.mkdir(parents=True)
            (dev / "idVendor").write_text("0781\n")
            (dev / "idProduct").write_text("5581\n")
            (dev / "manufacturer").write_text("SanDisk\n")
            (dev / "product").write_text("Ultra\n")
            (dev / "speed").write_text("480\n")
            (dev / "bDeviceClass").write_text("00\n")
            (iface / "bInterfaceClass").write_text("08\n")
            with self.settings(USB_SYSFS_ROOT=str(root)):
                payload = hostops.list_usb_devices()
        self.assertTrue(payload["available"])
        self.assertEqual(payload["devices"][0]["kind"], "Storage")
        self.assertEqual(payload["devices"][0]["name"], "SanDisk Ultra")

    def test_unmount_rejects_system_path(self):
        from dashboard import hostops

        ok, message = hostops.unmount_path("/etc")
        self.assertFalse(ok)
        self.assertIn("not a removable", message)

    def test_library_restart_requires_install(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("api_service_restart", args=["pihole"]))
        self.assertEqual(resp.status_code, 404)
