from pathlib import Path

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from library.catalog import SERVICES, get_docker_spec, get_service_by_slug
from library.installer import NO_CARD_ON_INSTALL, TUNNEL_SLUG, create_dashboard_card


# Official image listen ports when they differ from the host hint we publish.
EXPECTED_CONTAINER_PORTS = {
    "nextcloud": 80,
    "vaultwarden": 80,
    "filebrowser": 80,
    "audiobookshelf": 80,
    "speedtest-tracker": 80,
    "mealie": 9000,
}


class DockerSpecPortTests(SimpleTestCase):
    def test_nextcloud_maps_host_hint_to_apache_80(self):
        spec = get_docker_spec(get_service_by_slug("nextcloud"))
        self.assertEqual(spec["container_port"], 80)
        self.assertEqual(spec["host_port_hint"], 8080)
        self.assertIn('"8080:80"', get_service_by_slug("nextcloud")["compose"])

    def test_mismatched_listen_ports_are_explicit(self):
        for slug, container_port in EXPECTED_CONTAINER_PORTS.items():
            spec = get_docker_spec(get_service_by_slug(slug))
            self.assertEqual(
                spec["container_port"],
                container_port,
                f"{slug} must publish to container port {container_port}",
            )
            self.assertNotEqual(
                spec["container_port"],
                spec["host_port_hint"],
                f"{slug} host hint should stay free of the listen port",
            )

    def test_matching_ports_still_parse(self):
        spec = get_docker_spec(get_service_by_slug("jellyfin"))
        self.assertEqual(spec["container_port"], 8096)
        self.assertEqual(spec["host_port_hint"], 8096)

    def test_every_compose_service_has_a_numeric_container_port(self):
        for entry in SERVICES:
            if "ports:" not in (entry.get("compose") or ""):
                continue
            spec = get_docker_spec(entry)
            self.assertIsInstance(spec["container_port"], int)
            self.assertGreater(spec["container_port"], 0)


class DashboardCardTests(TestCase):
    def test_kuma_card_is_not_misc(self):
        entry = get_service_by_slug("uptime-kuma")
        service = create_dashboard_card("uptime-kuma", entry, 3001)
        self.assertFalse(service.is_misc)
        self.assertEqual(service.catalog_slug, "uptime-kuma")

    def test_nextcloud_card_is_not_misc(self):
        entry = get_service_by_slug("nextcloud")
        service = create_dashboard_card("nextcloud", entry, 8080)
        self.assertFalse(service.is_misc)


class LibrarySearchTests(TestCase):
    def test_library_page_has_search(self):
        admin = User.objects.create_user("admin", password="x", is_superuser=True)
        self.client.force_login(admin)
        resp = self.client.get(reverse("library"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="library-search"')
        self.assertContains(resp, 'id="library-empty"')
        self.assertContains(resp, 'id="uninstall-remove-data"')
        self.assertContains(resp, 'id="uninstall-remove-data" checked')

    def test_installed_kuma_has_open_link(self):
        from library.models import InstalledService

        admin = User.objects.create_user("admin", password="x", is_superuser=True)
        InstalledService.objects.create(
            slug="uptime-kuma",
            container_name="cc-uptime-kuma",
            host_port=3001,
            status=InstalledService.Status.RUNNING,
        )
        self.client.force_login(admin)
        resp = self.client.get(reverse("library"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, ">Open</a>")
        self.assertContains(resp, ":3001/")

    def test_filter_script_matches_name_and_slug(self):
        source = Path(__file__).resolve().parents[1] / "static" / "js" / "library.js"
        text = source.read_text(encoding="utf-8")
        self.assertIn("library-search", text)
        self.assertIn("cardSearchText", text)
        self.assertIn("library-card__name", text)
        self.assertIn("dataset.slug", text)

    def test_query_param_applies_search(self):
        source = Path(__file__).resolve().parents[1] / "static" / "js" / "library.js"
        text = source.read_text(encoding="utf-8")
        self.assertIn('params.get("q")', text)
        self.assertIn('params.get("search")', text)
        self.assertIn("applyFilters()", text)

    def test_kuma_install_skips_dashboard_card(self):
        self.assertIn("uptime-kuma", NO_CARD_ON_INSTALL)
        self.assertIn(TUNNEL_SLUG, NO_CARD_ON_INSTALL)

    def test_github_stays_in_actions_column(self):
        root = Path(__file__).resolve().parents[1]
        card = (root / "templates" / "library" / "_card.html").read_text(encoding="utf-8")
        css = (root / "static" / "css" / "library.css").read_text(encoding="utf-8")
        self.assertIn('class="library-card__actions-main"', card)
        self.assertLess(
            card.index("library-card__actions-main"),
            card.index("library-github-btn"),
        )
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto", css)
        self.assertNotIn("margin-left: auto", css)
        self.assertIn("library-add-card-btn", card)
        self.assertIn('aria-label="Add card"', card)
        self.assertNotIn(">Add card</a>", card)


class CloudflareTunnelTests(TestCase):
    def setUp(self):
        from library.models import InstalledService

        self.admin = User.objects.create_user("admin", password="x", is_superuser=True)
        InstalledService.objects.create(
            slug="cloudflare-tunnel",
            container_name="cc-cloudflare-tunnel",
            host_port=0,
            status=InstalledService.Status.STOPPED,
        )

    def test_settings_hides_cloudflare_until_installed(self):
        from library.models import InstalledService

        InstalledService.objects.filter(slug="cloudflare-tunnel").delete()
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("settings") + "?section=tunnel")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Cloudflare Tunnel is not installed.", html)
        self.assertIn("Install Cloudflare Tunnel", html)
        self.assertIn("q=cloudflare-tunnel", html)
        self.assertIn('id="tunnel-installed-settings" hidden', html)
        self.assertNotIn('id="tunnel-not-installed" hidden', html)

    def test_settings_shows_link_form_when_installed(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("settings") + "?section=tunnel")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('id="tunnel-not-installed" hidden', html)
        self.assertIn('id="tunnel-api-token"', html)
        self.assertIn(">Connect</button>", html)

    def test_catalog_has_no_published_port(self):
        entry = get_service_by_slug("cloudflare-tunnel")
        self.assertIsNotNone(entry)
        self.assertNotIn("ports:", entry["compose"])
        spec = get_docker_spec(entry)
        self.assertEqual(spec["image"], "cloudflare/cloudflared:latest")

    def test_install_does_not_open_port_or_add_card(self):
        from unittest.mock import MagicMock, patch

        from dashboard.models import Service
        from library.installer import _install_worker
        from library.models import InstalledService

        InstalledService.objects.filter(slug="cloudflare-tunnel").update(
            status=InstalledService.Status.INSTALLING,
        )
        client = MagicMock()
        client.images.get.return_value.attrs = {"Config": {"Labels": {}}}
        client.images.get.return_value.tags = ["cloudflare/cloudflared:latest"]
        with patch("library.installer.get_docker_client", return_value=client):
            _install_worker("cloudflare-tunnel")
        row = InstalledService.objects.get(slug="cloudflare-tunnel")
        self.assertEqual(row.host_port, 0)
        self.assertEqual(row.status, InstalledService.Status.STOPPED)
        client.containers.run.assert_not_called()
        self.assertFalse(Service.objects.filter(catalog_slug="cloudflare-tunnel").exists())

    def test_control_center_publish_is_blocked(self):
        from library.cloudflare import is_control_center_target

        self.assertTrue(is_control_center_target(origin_url="http://192.168.0.40:8099/"))
        self.assertTrue(is_control_center_target(catalog_slug="cloudflare-tunnel"))
        self.assertTrue(is_control_center_target(port=8099))
        self.assertFalse(is_control_center_target(origin_url="http://192.168.0.40:8080/"))

    def test_publish_api_rejects_control_center(self):
        from core.models import SiteSettings

        site = SiteSettings.load()
        site.cf_api_token = "token"
        site.cf_account_id = "acc"
        site.cf_zone_id = "zone"
        site.cf_zone_name = "example.com"
        site.cf_tunnel_id = "tun"
        site.cf_tunnel_token = "tt"
        site.save()
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("api_tunnel_publish"),
            data='{"hostname":"cc.example.com","host_port":8099,"slug":"nextcloud"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("LAN", resp.json()["error"])

    def test_auth_error_explains_tunnel_permission(self):
        from library.cloudflare import AUTH_HINT, _api_error_message

        self.assertEqual(
            _api_error_message(
                {"errors": [{"code": 10000, "message": "Authentication error"}]},
                403,
            ),
            AUTH_HINT,
        )

    def test_token_url_prefills_tunnel_and_all_resources(self):
        from library.cloudflare import token_create_url

        url = token_create_url()
        self.assertIn("argotunnel", url)
        self.assertIn("accountId=*", url)
        self.assertIn("zoneId=all", url)
        self.assertNotIn("cftunnel", url)

    def test_link_uses_zones_when_accounts_empty(self):
        from unittest.mock import patch

        from core.models import SiteSettings
        from library import cloudflare as cf

        class FakeSession:
            def request(self, method, url, **kwargs):
                class Resp:
                    status_code = 200

                    def json(self_inner):
                        if url.endswith("/accounts"):
                            return {"success": True, "result": []}
                        if "/zones" in url:
                            return {
                                "success": True,
                                "result": [
                                    {
                                        "id": "zone1",
                                        "name": "example.com",
                                        "account": {"id": "acc1", "name": "Home"},
                                    }
                                ],
                            }
                        if url.rstrip("/").endswith("/cfd_tunnel"):
                            if method == "GET":
                                return {"success": True, "result": []}
                            return {
                                "success": True,
                                "result": {"id": "tun1", "token": "tunnel-token"},
                            }
                        return {"success": True, "result": {}}

                return Resp()

        cf.set_http_session(FakeSession())
        self.addCleanup(lambda: cf.set_http_session(None))
        with patch("library.cloudflare.start_connector"):
            self.client.force_login(self.admin)
            resp = self.client.post(
                reverse("api_tunnel_link"),
                data='{"token":"cf-api-token","confirm":true}',
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))
        site = SiteSettings.load()
        self.assertEqual(site.cf_account_id, "acc1")
        self.assertEqual(site.cf_zone_name, "example.com")

    def test_link_stores_token_and_starts_connector(self):
        from unittest.mock import patch

        from core.models import SiteSettings
        from library import cloudflare as cf

        class FakeSession:
            def request(self, method, url, **kwargs):
                class Resp:
                    status_code = 200

                    def json(self_inner):
                        if url.endswith("/accounts"):
                            return {
                                "success": True,
                                "result": [{"id": "acc1", "name": "Home"}],
                            }
                        if "/zones" in url:
                            return {
                                "success": True,
                                "result": [
                                    {
                                        "id": "zone1",
                                        "name": "example.com",
                                        "account": {"id": "acc1"},
                                    }
                                ],
                            }
                        if url.rstrip("/").endswith("/cfd_tunnel"):
                            if method == "GET":
                                return {"success": True, "result": []}
                            return {
                                "success": True,
                                "result": {"id": "tun1", "token": "tunnel-token"},
                            }
                        return {"success": True, "result": {}}

                return Resp()

        cf.set_http_session(FakeSession())
        self.addCleanup(lambda: cf.set_http_session(None))
        with patch("library.cloudflare.start_connector") as start:
            self.client.force_login(self.admin)
            preview = self.client.post(
                reverse("api_tunnel_link"),
                data='{"token":"cf-api-token"}',
                content_type="application/json",
            )
            self.assertEqual(preview.status_code, 200)
            self.assertTrue(preview.json().get("preview"))
            start.assert_not_called()
            resp = self.client.post(
                reverse("api_tunnel_link"),
                data='{"token":"cf-api-token","account_id":"acc1","zone_id":"zone1","confirm":true}',
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))
        start.assert_called_once()
        site = SiteSettings.load()
        self.assertEqual(site.cf_api_token, "cf-api-token")
        self.assertEqual(site.cf_tunnel_id, "tun1")
        self.assertEqual(site.cf_tunnel_token, "tunnel-token")

    def test_ingress_origin_strips_path(self):
        from library.cloudflare import ingress_origin, origin_for_service

        self.assertEqual(
            ingress_origin("http://192.168.0.40:80/admin/"),
            "http://192.168.0.40:80",
        )
        self.assertEqual(
            ingress_origin("http://192.168.0.40:2283/"),
            "http://192.168.0.40:2283",
        )

    def test_origin_ignores_public_zone_href(self):
        from core.models import SiteSettings
        from dashboard.models import Service, ServiceCategory
        from library.cloudflare import origin_for_service

        site = SiteSettings.load()
        site.cf_zone_name = "thezaidan.family"
        site.services_host = "192.168.0.40"
        site.save()
        cat = ServiceCategory.objects.create(name="Apps")
        service = Service.objects.create(
            category=cat,
            name="AIO",
            href="https://aiometadata.thezaidan.family/",
            host="192.168.0.40",
            port=7070,
            enabled=True,
        )
        self.assertEqual(origin_for_service(service=service), "http://192.168.0.40:7070")
        pihole = Service.objects.create(
            category=cat,
            name="Pi-hole",
            href="http://192.168.0.40:80/admin/",
            host="192.168.0.40",
            port=80,
            catalog_slug="pihole",
            path="/admin/",
            enabled=True,
        )
        self.assertEqual(origin_for_service(service=pihole), "http://192.168.0.40:80")

    def test_compose_hostname_appends_zone(self):
        from library.cloudflare import compose_hostname

        self.assertEqual(
            compose_hostname(subdomain="photos", zone_name="example.com"),
            "photos.example.com",
        )
        self.assertEqual(
            compose_hostname(hostname="photos.example.com", zone_name="example.com"),
            "photos.example.com",
        )
        with self.assertRaises(RuntimeError):
            compose_hostname(subdomain="photos.other.com", zone_name="example.com")

    def test_publish_subdomain_appends_zone(self):
        from unittest.mock import patch

        from core.models import SiteSettings
        from dashboard.models import Service, ServiceCategory
        from library.models import TunnelRoute

        site = SiteSettings.load()
        site.cf_api_token = "token"
        site.cf_account_id = "acc"
        site.cf_zone_id = "zone"
        site.cf_zone_name = "example.com"
        site.cf_tunnel_id = "tun"
        site.cf_tunnel_token = "tt"
        site.save()
        cat = ServiceCategory.objects.create(name="Apps")
        service = Service.objects.create(
            category=cat,
            name="Photos",
            href="http://192.168.0.40:2283/",
            catalog_slug="immich",
            enabled=True,
        )
        self.client.force_login(self.admin)
        with patch("library.cloudflare._sync_ingress") as sync, patch(
            "library.cloudflare._ensure_cname"
        ) as cname:
            resp = self.client.post(
                reverse("api_tunnel_publish"),
                data=f'{{"subdomain":"photos","service_id":{service.id}}}',
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        sync.assert_called_once()
        cname.assert_called_once()
        self.assertTrue(TunnelRoute.objects.filter(hostname="photos.example.com").exists())
        self.assertEqual(
            TunnelRoute.objects.get(hostname="photos.example.com").origin_url,
            "http://192.168.0.40:2283",
        )
