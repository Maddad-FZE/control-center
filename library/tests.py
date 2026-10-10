from pathlib import Path
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from library.catalog import all_services, get_docker_spec, get_service_by_slug
from library.installer import NO_CARD_ON_INSTALL, TUNNEL_SLUG, create_dashboard_card


# Official image listen ports when they differ from the host hint we publish.
EXPECTED_CONTAINER_PORTS = {
    "nextcloud": 80,
    "vaultwarden": 80,
    "filebrowser": 80,
    "audiobookshelf": 80,
    "speedtest-tracker": 80,
    "mealie": 9000,
    "it-tools": 80,
    "wallos": 80,
    "bookstack": 80,
    "open-webui": 8080,
    "changedetection": 5000,
    "securo": 8080,
}


class DockerSpecPortTests(TestCase):
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
        for entry in all_services():
            if "ports:" not in (entry.get("compose") or ""):
                continue
            spec = get_docker_spec(entry)
            self.assertIsInstance(spec["container_port"], int)
            self.assertGreater(spec["container_port"], 0)

    def test_nextcloud_keeps_single_service_compose(self):
        entry = get_service_by_slug("nextcloud")
        self.assertEqual(entry["install_options"], "admin-credentials")
        self.assertNotIn("postgres", entry["compose"])
        spec = get_docker_spec(entry)
        self.assertEqual(spec["container_port"], 80)
        self.assertEqual(spec["image"], "nextcloud:latest")


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


class IconResolveTests(TestCase):
    def test_known_slug_uses_bundled_icon_list(self):
        from library.icons import icon_url_for_entry

        url = icon_url_for_entry("pihole", "https://cdn.simpleicons.org/pihole")
        self.assertTrue(url.endswith("/E87722") or "/E87722" in url)
        self.assertIn("pihole", url)

    def test_unknown_slug_keeps_original_icon(self):
        from library.icons import icon_url_for_entry

        original = "https://api.iconify.design/mdi/access-point.svg?color=%23e87722"
        self.assertEqual(icon_url_for_entry("matter", original, name="Matter"), original)

    def test_matter_is_in_the_catalog(self):
        entry = get_service_by_slug("matter")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["category"], "Home Automation")
        self.assertEqual(entry["default_port"], 5580)


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
        self.assertContains(resp, 'id="install-credentials-modal"')
        self.assertContains(resp, 'data-credentials="1"')
        self.assertContains(resp, 'data-slug="matter"')
        self.assertContains(resp, "Matter")
        self.assertContains(resp, "api.iconify.design/mdi/access-point")

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
        self.assertIn("validateCredentials", text)
        self.assertIn("admin_password", text)
        self.assertIn('dataset.credentials === "1"', text)

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
        self.assertTrue(is_control_center_target(origin_url="http://192.168.0.40/"))
        self.assertTrue(is_control_center_target(catalog_slug="cloudflare-tunnel"))
        self.assertTrue(is_control_center_target(port=80))
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
            data='{"hostname":"cc.example.com","host_port":80,"slug":"nextcloud"}',
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

    def test_public_href_uses_https_and_keeps_path(self):
        from library.cloudflare import public_href

        self.assertEqual(public_href(""), "")
        self.assertEqual(
            public_href("photos.example.com", "http://192.168.0.40:2283/"),
            "https://photos.example.com/",
        )
        self.assertEqual(
            public_href("pihole.example.com", "http://192.168.0.40:80/admin/"),
            "https://pihole.example.com/admin/",
        )

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


class NextcloudInstallTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin", password="x", is_superuser=True)

    def _post_install(self, slug, payload=None):
        kwargs = {}
        if payload is not None:
            kwargs["data"] = json.dumps(payload)
            kwargs["content_type"] = "application/json"
        return self.client.post(reverse("api_service_install", args=[slug]), **kwargs)

    def test_install_api_rejects_missing_password(self):
        self.client.force_login(self.admin)
        resp = self._post_install("nextcloud", {"admin_user": "admin"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("10 characters", resp.json()["error"])

    def test_install_api_rejects_weak_password(self):
        self.client.force_login(self.admin)
        resp = self._post_install(
            "nextcloud",
            {"admin_user": "admin", "admin_password": "short"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("10 characters", resp.json()["error"])

    def test_install_api_rejects_bad_username(self):
        self.client.force_login(self.admin)
        resp = self._post_install(
            "nextcloud",
            {"admin_user": "bad user", "admin_password": "longenough1"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("username", resp.json()["error"].lower())

    def test_other_services_accept_empty_body(self):
        from unittest.mock import patch

        self.client.force_login(self.admin)
        with patch("library.views.start_install", return_value=(True, "Installing")) as mocked:
            resp = self._post_install("pihole")
        self.assertEqual(resp.status_code, 200)
        mocked.assert_called_once()
        self.assertIsNone(mocked.call_args.kwargs.get("install_options"))

    def test_install_api_passes_credentials(self):
        from unittest.mock import patch

        self.client.force_login(self.admin)
        with patch("library.views.start_install", return_value=(True, "Installing")) as mocked:
            resp = self._post_install(
                "nextcloud",
                {"admin_user": "admin", "admin_password": "longenough1"},
            )
        self.assertEqual(resp.status_code, 200)
        options = mocked.call_args.kwargs["install_options"]
        self.assertEqual(options["admin_user"], "admin")
        self.assertEqual(options["admin_password"], "longenough1")

    def _mock_docker(self, existing_db_env=None):
        from unittest.mock import MagicMock

        import docker

        client = MagicMock()
        client.images.get.return_value.attrs = {"Config": {"Labels": {}}}
        client.images.get.return_value.tags = ["nextcloud:latest"]
        client.containers.list.return_value = []
        client.networks.get.side_effect = docker.errors.NotFound("missing")

        db_container = MagicMock()
        db_container.exec_run.return_value.exit_code = 0
        if existing_db_env is not None:
            db_container.attrs = {"Config": {"Env": existing_db_env}}
        have_db = {"yes": existing_db_env is not None}

        def get_container(name):
            if name == "cc-nextcloud-db" and have_db["yes"]:
                return db_container
            raise docker.errors.NotFound("missing")

        client.containers.get.side_effect = get_container
        runs = []

        def run(*args, **kwargs):
            runs.append(kwargs)
            if kwargs.get("name") == "cc-nextcloud-db":
                have_db["yes"] = True
                return db_container
            return MagicMock()

        client.containers.run.side_effect = run
        client._runs = runs
        return client

    def test_worker_creates_app_and_db_on_shared_network(self):
        from unittest.mock import patch

        from dashboard.models import Service
        from library.installer import NEXTCLOUD_NETWORK, _install_worker
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="nextcloud",
            container_name="cc-nextcloud",
            status=InstalledService.Status.INSTALLING,
        )
        client = self._mock_docker()
        with patch("library.installer.get_docker_client", return_value=client), patch(
            "library.installer._wait_for_nextcloud", return_value=True
        ), patch("library.installer.secrets.token_urlsafe", return_value="generated-db-secret"):
            _install_worker(
                "nextcloud",
                {"admin_user": "admin", "admin_password": "longenough1"},
            )
        runs = {row["name"]: row for row in client._runs}
        self.assertEqual(set(runs), {"cc-nextcloud", "cc-nextcloud-db"})
        db_run = runs["cc-nextcloud-db"]
        app_run = runs["cc-nextcloud"]
        self.assertNotIn("ports", db_run)
        self.assertEqual(app_run["ports"], {"80/tcp": 8080})
        self.assertEqual(db_run["network"], NEXTCLOUD_NETWORK)
        self.assertEqual(app_run["network"], NEXTCLOUD_NETWORK)
        self.assertEqual(db_run["environment"]["POSTGRES_PASSWORD"], "generated-db-secret")
        self.assertEqual(app_run["environment"]["POSTGRES_PASSWORD"], "generated-db-secret")
        self.assertEqual(app_run["environment"]["POSTGRES_HOST"], "cc-nextcloud-db")
        self.assertEqual(app_run["environment"]["NEXTCLOUD_ADMIN_USER"], "admin")
        self.assertEqual(app_run["environment"]["NEXTCLOUD_ADMIN_PASSWORD"], "longenough1")
        self.assertNotIn("NEXTCLOUD_ADMIN_PASSWORD", db_run["environment"])
        self.assertEqual(db_run["labels"]["control-center.role"], "db")
        row = InstalledService.objects.get(slug="nextcloud")
        self.assertEqual(row.status, InstalledService.Status.RUNNING)
        self.assertEqual(row.host_port, 8080)
        self.assertTrue(Service.objects.filter(catalog_slug="nextcloud").exists())

    def test_reinstall_reuses_existing_db_password(self):
        from unittest.mock import patch

        from library.installer import _install_worker
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="nextcloud",
            container_name="cc-nextcloud",
            status=InstalledService.Status.INSTALLING,
        )
        client = self._mock_docker(
            existing_db_env=["POSTGRES_PASSWORD=reused-secret", "POSTGRES_USER=nextcloud"]
        )
        with patch("library.installer.get_docker_client", return_value=client), patch(
            "library.installer._wait_for_nextcloud", return_value=True
        ), patch("library.installer.secrets.token_urlsafe", return_value="should-not-use"):
            _install_worker(
                "nextcloud",
                {"admin_user": "admin", "admin_password": "longenough1"},
            )
        runs = {row["name"]: row for row in client._runs}
        self.assertEqual(runs["cc-nextcloud-db"]["environment"]["POSTGRES_PASSWORD"], "reused-secret")
        self.assertEqual(runs["cc-nextcloud"]["environment"]["POSTGRES_PASSWORD"], "reused-secret")

    def test_uninstall_removes_db_volumes_and_network(self):
        from unittest.mock import MagicMock, patch

        from dashboard.models import Service
        from library.installer import uninstall
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="nextcloud",
            container_name="cc-nextcloud",
            host_port=8082,
            status=InstalledService.Status.RUNNING,
        )
        create_dashboard_card("nextcloud", get_service_by_slug("nextcloud"), 8082)
        client = MagicMock()
        vol_html = MagicMock()
        vol_html.name = "cc-nextcloud-0"
        vol_html.attrs = {"Labels": {"control-center.slug": "nextcloud"}}
        vol_db = MagicMock()
        vol_db.name = "cc-nextcloud-db-0"
        vol_db.attrs = {"Labels": {}}
        client.volumes.list.return_value = [vol_html, vol_db]
        net = MagicMock()
        client.networks.get.return_value = net
        with patch("library.installer.get_docker_client", return_value=client):
            ok, message = uninstall("nextcloud", remove_data=True)
        self.assertTrue(ok)
        names = [call.args[0] for call in client.containers.get.call_args_list]
        self.assertIn("cc-nextcloud", names)
        self.assertIn("cc-nextcloud-db", names)
        vol_html.remove.assert_called()
        vol_db.remove.assert_called()
        client.networks.get.assert_called_with("cc-nextcloud-net")
        net.remove.assert_called()
        self.assertFalse(InstalledService.objects.filter(slug="nextcloud").exists())
        self.assertFalse(Service.objects.filter(catalog_slug="nextcloud").exists())
        self.assertEqual(message, "Uninstalled")


class CatalogApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin", password="x", is_superuser=True)
        self.client.force_login(self.admin)

    def test_settings_has_library_repositories_editor(self):
        resp = self.client.get(reverse("settings") + "?section=platform")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Library repositories")
        self.assertContains(resp, 'id="library-repos-edit-btn"')
        self.assertContains(resp, "library-repos.js")

    def test_catalog_list_returns_seeded_entries(self):
        resp = self.client.get(reverse("api_catalog_list"))
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(any(row["slug"] == "jellyfin" for row in items))

    def test_apply_keeps_manual_and_installed_apps(self):
        from unittest.mock import patch

        from library.catalog_store import apply_catalog
        from library.models import CatalogItem, InstalledService

        CatalogItem.objects.filter(slug="jellyfin").update(name="Old Jellyfin")
        InstalledService.objects.create(
            slug="pihole",
            container_name="cc-pihole",
            host_port=80,
            status="running",
        )
        CatalogItem.objects.create(
            slug="my-app",
            name="Mine",
            category="Custom",
            compose="services:\n  app:\n    image: demo:latest\n",
            default_port=9,
            is_builtin=False,
        )
        apps = [
            {
                "slug": "jellyfin",
                "name": "Jellyfin Remote",
                "tagline": "Media",
                "description": "Updated blurb",
                "category": "Media",
                "repo": "jellyfin/jellyfin",
                "website": "https://jellyfin.org/",
                "icon": "",
                "default_port": 8096,
                "container_port": 0,
                "path": "/",
                "widget_type": "none",
                "compose": "services:\n  jellyfin:\n    image: jellyfin/jellyfin\n",
                "install_options": "",
                "is_builtin": True,
                "sort_order": 1,
            },
            {
                "slug": "my-app",
                "name": "Remote copy",
                "tagline": "",
                "description": "should not win",
                "category": "Custom",
                "repo": "example/my-app",
                "website": "",
                "icon": "",
                "default_port": 9,
                "container_port": 0,
                "path": "/",
                "widget_type": "none",
                "compose": "services:\n  app:\n    image: other:latest\n",
                "install_options": "",
                "is_builtin": True,
                "sort_order": 2,
            },
            {
                "slug": "remote-only",
                "name": "Remote Only",
                "tagline": "",
                "description": "New",
                "category": "Tools",
                "repo": "example/remote",
                "website": "",
                "icon": "",
                "default_port": 8080,
                "container_port": 0,
                "path": "/",
                "widget_type": "none",
                "compose": "services:\n  app:\n    image: remote:latest\n",
                "install_options": "",
                "is_builtin": True,
                "sort_order": 3,
            },
        ]
        with patch("library.catalog_store._slug_has_data_volumes", return_value=False):
            counts = apply_catalog(apps)
        self.assertEqual(CatalogItem.objects.get(slug="jellyfin").name, "Jellyfin Remote")
        self.assertFalse(CatalogItem.objects.filter(slug="glances").exists())
        self.assertTrue(CatalogItem.objects.filter(slug="pihole").exists())
        mine = CatalogItem.objects.get(slug="my-app")
        self.assertEqual(mine.name, "Mine")
        self.assertFalse(mine.is_builtin)
        self.assertTrue(CatalogItem.objects.filter(slug="remote-only", is_builtin=True).exists())
        self.assertGreaterEqual(counts["updated"], 1)
        self.assertEqual(counts["added"], 1)
        self.assertGreaterEqual(counts["removed"], 1)
        self.assertEqual(counts["kept_manual"], 1)
        self.assertGreaterEqual(counts["kept_installed"], 1)

    def test_fetch_rejects_bad_host_schema_and_invalid_app(self):
        from unittest.mock import MagicMock, patch

        from library.catalog_store import fetch_catalog
        from library.models import CatalogItem

        before = CatalogItem.objects.count()
        apps, error = fetch_catalog("https://evil.example/apps.json")
        self.assertIsNone(apps)
        self.assertIn("raw.githubusercontent.com", error)

        def fake_response(payload):
            resp = MagicMock()
            resp.ok = True
            resp.status_code = 200
            resp.url = "https://raw.githubusercontent.com/Maddad-FZE/control-center/main/catalog/apps.json"
            resp.content = b"{}"
            resp.json.return_value = payload
            return resp

        url = "https://raw.githubusercontent.com/Maddad-FZE/control-center/main/catalog/apps.json"
        with patch("library.catalog_store.requests.get", return_value=fake_response({"schema": 2, "apps": []})):
            apps, error = fetch_catalog(url)
        self.assertIsNone(apps)
        self.assertIn("schema", error)
        with patch(
            "library.catalog_store.requests.get",
            return_value=fake_response(
                {
                    "schema": 1,
                    "apps": [
                        {
                            "slug": "nope",
                            "name": "",
                            "category": "Tools",
                            "compose": "services:\n  a:\n    image: a\n",
                            "default_port": 80,
                        }
                    ],
                }
            ),
        ):
            apps, error = fetch_catalog(url)
        self.assertIsNone(apps)
        self.assertIn("Name", error)
        self.assertEqual(CatalogItem.objects.count(), before)

    def test_empty_database_seeds_from_bundled_file(self):
        from library.catalog_store import ensure_catalog_seeded
        from library.models import CatalogItem

        CatalogItem.objects.all().delete()
        ensure_catalog_seeded()
        jellyfin = CatalogItem.objects.get(slug="jellyfin")
        self.assertTrue(jellyfin.is_builtin)
        self.assertTrue(jellyfin.description)
        self.assertIn("image:", jellyfin.compose)

    def test_member_cannot_refresh_catalog(self):
        member = User.objects.create_user("member", password="x")
        self.client.force_login(member)
        resp = self.client.post(reverse("api_catalog_refresh"))
        self.assertEqual(resp.status_code, 403)

    def test_create_update_and_delete_custom_entry(self):
        compose = (
            "services:\n  demo:\n    image: demo:latest\n    ports:\n"
            '      - "9090:80"\n'
        )
        create = self.client.post(
            reverse("api_catalog_create"),
            data=json.dumps(
                {
                    "slug": "demo-app",
                    "name": "Demo App",
                    "category": "Testing",
                    "compose": compose,
                    "default_port": 9090,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create.status_code, 200)
        update = self.client.post(
            reverse("api_catalog_save", args=["demo-app"]),
            data=json.dumps(
                {
                    "slug": "demo-app",
                    "name": "Demo App Renamed",
                    "category": "Testing",
                    "compose": compose,
                    "default_port": 9090,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(update.status_code, 200)
        entry = get_service_by_slug("demo-app")
        self.assertEqual(entry["name"], "Demo App Renamed")
        delete = self.client.post(reverse("api_catalog_delete", args=["demo-app"]))
        self.assertEqual(delete.status_code, 200)
        self.assertIsNone(get_service_by_slug("demo-app"))

    def test_delete_blocked_when_installed(self):
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="jellyfin",
            container_name="cc-jellyfin",
            host_port=8096,
            status=InstalledService.Status.RUNNING,
        )
        resp = self.client.post(reverse("api_catalog_delete", args=["jellyfin"]))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Uninstall", resp.json()["error"])


class PiholeInstallTests(TestCase):
    def test_docker_spec_includes_config_volume(self):
        spec = get_docker_spec(get_service_by_slug("pihole"))
        self.assertIn("/etc/pihole", spec["volumes"])

    def test_worker_sets_password_vault_and_widget_key(self):
        from unittest.mock import MagicMock, patch

        import docker as docker_sdk
        from core.models import VaultEntry
        from dashboard.models import Service
        from library.installer import _install_worker
        from library.models import InstalledService

        admin = User.objects.create_user("boss", password="secret", is_superuser=True)
        InstalledService.objects.create(
            slug="pihole",
            container_name="cc-pihole",
            status=InstalledService.Status.INSTALLING,
        )
        client = MagicMock()
        client.containers.list.return_value = []
        client.containers.get.side_effect = docker_sdk.errors.NotFound("missing")
        client.containers.run.return_value = MagicMock()
        with patch("library.installer.get_docker_client", return_value=client), patch(
            "library.installer.pick_host_port", return_value=8089
        ), patch(
            "library.installer.secrets.token_urlsafe", return_value="pihole-secret"
        ), patch(
            "library.installer._image_version", return_value="latest"
        ):
            _install_worker("pihole", {"user_id": admin.id})
        kwargs = client.containers.run.call_args.kwargs
        self.assertEqual(kwargs["name"], "cc-pihole")
        self.assertEqual(
            kwargs["environment"]["FTLCONF_webserver_api_password"], "pihole-secret"
        )
        binds = [row["bind"] for row in (kwargs["volumes"] or {}).values()]
        self.assertIn("/etc/pihole", binds)
        service = Service.objects.get(catalog_slug="pihole")
        self.assertEqual(service.widget_api_key, "pihole-secret")
        stored = VaultEntry.objects.get(user=admin, service=service)
        self.assertEqual(stored.secret_ciphertext, "pihole-secret")
        self.assertEqual(stored.label, "Pi-hole")


class NewCatalogAppTests(TestCase):
    def test_glances_uses_host_pid(self):
        spec = get_docker_spec(get_service_by_slug("glances"))
        self.assertEqual(spec["pid_mode"], "host")
        self.assertEqual(spec["container_port"], 61208)
        self.assertEqual(spec["image"], "nicolargo/glances:latest-full")
        self.assertEqual(spec["env"].get("GLANCES_OPT"), "-w")

    def test_open_webui_uses_host_gateway(self):
        spec = get_docker_spec(get_service_by_slug("open-webui"))
        self.assertEqual(spec["container_port"], 8080)
        self.assertEqual(spec["host_port_hint"], 3000)
        self.assertEqual(spec["extra_hosts"].get("host.docker.internal"), "host-gateway")
        self.assertIn("11434", spec["env"].get("OLLAMA_BASE_URL", ""))

    def test_named_apps_are_in_the_catalog(self):
        for slug, category in (
            ("glances", "Monitoring"),
            ("changedetection", "Monitoring"),
            ("kavita", "Media"),
            ("linkding", "Productivity"),
            ("stirling-pdf", "Productivity"),
            ("it-tools", "Productivity"),
            ("wallos", "Productivity"),
            ("open-webui", "Productivity"),
            ("bookstack", "Productivity"),
            ("odysseus", "Productivity"),
            ("securo", "Productivity"),
            ("gods-eye-view", "Monitoring"),
            ("trek", "Productivity"),
            ("databasus", "Management and Hosting"),
            ("notediscovery", "Productivity"),
            ("snapotter", "Productivity"),
        ):
            entry = get_service_by_slug(slug)
            self.assertIsNotNone(entry, slug)
            self.assertEqual(entry["category"], category, slug)

    def test_page_load_does_not_restore_deleted_builtins(self):
        from library.catalog_store import ensure_catalog_seeded
        from library.models import CatalogItem

        ensure_catalog_seeded()
        CatalogItem.objects.filter(slug="glances").delete()
        ensure_catalog_seeded()
        self.assertFalse(CatalogItem.objects.filter(slug="glances").exists())

    def test_glances_worker_passes_pid_mode(self):
        from unittest.mock import MagicMock, patch

        import docker as docker_sdk
        from library.installer import _install_worker
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="glances",
            container_name="cc-glances",
            status=InstalledService.Status.INSTALLING,
        )
        client = MagicMock()
        client.containers.list.return_value = []
        client.containers.get.side_effect = docker_sdk.errors.NotFound("missing")
        client.containers.run.return_value = MagicMock()
        with patch("library.installer.get_docker_client", return_value=client), patch(
            "library.installer.pick_host_port", return_value=61208
        ), patch("library.installer._image_version", return_value="latest"):
            _install_worker("glances")
        kwargs = client.containers.run.call_args.kwargs
        self.assertEqual(kwargs["pid_mode"], "host")
        self.assertEqual(kwargs["name"], "cc-glances")


class ActualBudgetInstallTests(TestCase):
    def test_spec_sets_listen_port(self):
        spec = get_docker_spec(get_service_by_slug("actual-budget"))
        self.assertEqual(spec["container_port"], 5006)
        self.assertEqual(spec["env"].get("ACTUAL_PORT"), "5006")
        self.assertEqual(spec["image"], "actualbudget/actual-server:latest")

    def test_worker_sets_port_and_waits_for_listen(self):
        from unittest.mock import MagicMock, patch

        import docker as docker_sdk
        from dashboard.models import Service
        from library.installer import _install_worker
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="actual-budget",
            container_name="cc-actual-budget",
            status=InstalledService.Status.INSTALLING,
        )
        client = MagicMock()
        client.containers.list.return_value = []
        client.containers.get.side_effect = docker_sdk.errors.NotFound("missing")
        container = MagicMock()
        container.status = "running"
        container.logs.return_value = b"Listening on :::5006...\n"
        client.containers.run.return_value = container
        with patch("library.installer.get_docker_client", return_value=client), patch(
            "library.installer.pick_host_port", return_value=5006
        ), patch("library.installer._image_version", return_value="latest"):
            _install_worker("actual-budget")
        kwargs = client.containers.run.call_args.kwargs
        self.assertEqual(kwargs["name"], "cc-actual-budget")
        self.assertEqual(kwargs["environment"]["ACTUAL_PORT"], "5006")
        self.assertEqual(kwargs["environment"]["ACTUAL_HOSTNAME"], "::")
        self.assertEqual(kwargs["ports"], {"5006/tcp": 5006})
        container.reload.assert_called()
        row = InstalledService.objects.get(slug="actual-budget")
        self.assertEqual(row.status, InstalledService.Status.RUNNING)
        self.assertTrue(Service.objects.filter(catalog_slug="actual-budget").exists())

    def test_worker_surfaces_container_logs_when_process_exits(self):
        from unittest.mock import MagicMock, patch

        import docker as docker_sdk
        from library.installer import _install_worker
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="actual-budget",
            container_name="cc-actual-budget",
            status=InstalledService.Status.INSTALLING,
        )
        client = MagicMock()
        client.containers.list.return_value = []
        client.containers.get.side_effect = docker_sdk.errors.NotFound("missing")
        container = MagicMock()
        container.status = "exited"
        container.logs.return_value = b"EACCES: permission denied, open '/data/.migrate'\n"
        client.containers.run.return_value = container
        with patch("library.installer.get_docker_client", return_value=client), patch(
            "library.installer.pick_host_port", return_value=5006
        ):
            _install_worker("actual-budget")
        row = InstalledService.objects.get(slug="actual-budget")
        self.assertEqual(row.status, InstalledService.Status.ERROR)
        self.assertIn("EACCES", row.error)
        self.assertIn("exited", row.error.lower())


class BookstackInstallTests(TestCase):
    def _mock_docker(self):
        from unittest.mock import MagicMock

        import docker

        client = MagicMock()
        client.images.get.return_value.attrs = {"Config": {"Labels": {}}}
        client.images.get.return_value.tags = ["lscr.io/linuxserver/bookstack:latest"]
        client.containers.list.return_value = []
        client.networks.get.side_effect = docker.errors.NotFound("missing")
        db_container = MagicMock()
        db_container.exec_run.return_value.exit_code = 0
        client.containers.get.side_effect = docker.errors.NotFound("missing")
        runs = []

        def run(*args, **kwargs):
            runs.append(kwargs)
            if kwargs.get("name") == "cc-bookstack-db":
                return db_container
            return MagicMock()

        client.containers.run.side_effect = run
        client._runs = runs
        return client

    def test_worker_creates_app_and_mariadb(self):
        from unittest.mock import patch

        from dashboard.models import Service
        from library.installer import BOOKSTACK_NETWORK, _install_worker
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="bookstack",
            container_name="cc-bookstack",
            status=InstalledService.Status.INSTALLING,
        )
        client = self._mock_docker()
        with patch("library.installer.get_docker_client", return_value=client), patch(
            "library.installer.pick_host_port", return_value=6875
        ), patch("library.installer.secrets.token_urlsafe", return_value="db-secret"), patch(
            "library.installer._bookstack_app_key", return_value="base64:test-key"
        ):
            _install_worker("bookstack")
        runs = {row["name"]: row for row in client._runs}
        self.assertEqual(set(runs), {"cc-bookstack", "cc-bookstack-db"})
        db_run = runs["cc-bookstack-db"]
        app_run = runs["cc-bookstack"]
        self.assertEqual(db_run["network"], BOOKSTACK_NETWORK)
        self.assertEqual(app_run["network"], BOOKSTACK_NETWORK)
        self.assertEqual(app_run["ports"], {"80/tcp": 6875})
        self.assertEqual(db_run["environment"]["MYSQL_PASSWORD"], "db-secret")
        self.assertEqual(app_run["environment"]["DB_HOST"], "cc-bookstack-db")
        self.assertEqual(app_run["environment"]["DB_PASSWORD"], "db-secret")
        self.assertEqual(app_run["environment"]["APP_KEY"], "base64:test-key")
        self.assertIn("APP_URL", app_run["environment"])
        self.assertEqual(db_run["labels"]["control-center.role"], "db")
        row = InstalledService.objects.get(slug="bookstack")
        self.assertEqual(row.status, InstalledService.Status.RUNNING)
        self.assertTrue(Service.objects.filter(catalog_slug="bookstack").exists())

    def test_uninstall_removes_db_and_network(self):
        from unittest.mock import MagicMock, patch

        from library.installer import uninstall
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="bookstack",
            container_name="cc-bookstack",
            host_port=6875,
            status=InstalledService.Status.RUNNING,
        )
        create_dashboard_card("bookstack", get_service_by_slug("bookstack"), 6875)
        client = MagicMock()
        client.volumes.list.return_value = []
        net = MagicMock()
        client.networks.get.return_value = net
        with patch("library.installer.get_docker_client", return_value=client):
            ok, message = uninstall("bookstack", remove_data=True)
        self.assertTrue(ok)
        names = [call.args[0] for call in client.containers.get.call_args_list]
        self.assertIn("cc-bookstack", names)
        self.assertIn("cc-bookstack-db", names)
        client.networks.get.assert_called_with("cc-bookstack-net")
        net.remove.assert_called()
        self.assertEqual(message, "Uninstalled")


class OdysseusInstallTests(TestCase):
    def test_worker_builds_and_starts_sidecars(self):
        from unittest.mock import MagicMock, patch

        import docker as docker_sdk
        from dashboard.models import Service
        from library.installer import ODYSSEUS_NETWORK, _install_worker
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="odysseus",
            container_name="cc-odysseus",
            status=InstalledService.Status.INSTALLING,
        )
        client = MagicMock()
        client.api.build.return_value = iter([{}])
        client.containers.list.return_value = []
        client.containers.get.side_effect = docker_sdk.errors.NotFound("missing")
        client.networks.get.side_effect = docker_sdk.errors.NotFound("missing")
        runs = []

        def run(*args, **kwargs):
            runs.append(kwargs)
            return MagicMock()

        client.containers.run.side_effect = run
        with patch("library.installer.get_docker_client", return_value=client), patch(
            "library.installer.pick_host_port", return_value=7000
        ), patch("library.installer._image_version", return_value="local"):
            _install_worker("odysseus")
        names = {row["name"] for row in runs}
        self.assertEqual(
            names,
            {
                "cc-odysseus",
                "cc-odysseus-chroma",
                "cc-odysseus-searxng",
                "cc-odysseus-ntfy",
            },
        )
        app_run = next(row for row in runs if row["name"] == "cc-odysseus")
        self.assertEqual(app_run["network"], ODYSSEUS_NETWORK)
        self.assertEqual(app_run["ports"], {"7000/tcp": 7000})
        self.assertEqual(app_run["extra_hosts"]["host.docker.internal"], "host-gateway")
        self.assertEqual(app_run["environment"]["AUTH_ENABLED"], "true")
        self.assertTrue(client.api.build.called)
        self.assertEqual(client.api.build.call_args.kwargs["remote"].split("#")[0], "https://github.com/odysseus-dev/odysseus.git")
        self.assertTrue(Service.objects.filter(catalog_slug="odysseus").exists())
        row = InstalledService.objects.get(slug="odysseus")
        self.assertEqual(row.status, InstalledService.Status.RUNNING)


class SecuroInstallTests(TestCase):
    def _mock_docker(self):
        from unittest.mock import MagicMock

        import docker

        client = MagicMock()
        client.images.get.return_value.attrs = {"Config": {"Labels": {}}}
        client.images.get.return_value.tags = [
            "ghcr.io/securo-finance/securo-frontend:latest"
        ]
        client.containers.list.return_value = []
        client.networks.get.side_effect = docker.errors.NotFound("missing")
        ready = MagicMock()
        ready.exec_run.return_value.exit_code = 0
        client.containers.get.side_effect = docker.errors.NotFound("missing")
        runs = []

        def run(*args, **kwargs):
            runs.append(kwargs)
            if kwargs.get("name") in ("cc-securo-db", "cc-securo-redis"):
                return ready
            return MagicMock()

        client.containers.run.side_effect = run
        client._runs = runs
        return client

    def test_frontend_spec_uses_nginx_port(self):
        spec = get_docker_spec(get_service_by_slug("securo"))
        self.assertEqual(spec["container_port"], 8080)
        self.assertEqual(spec["host_port_hint"], 3030)
        self.assertEqual(spec["image"], "ghcr.io/securo-finance/securo-frontend:latest")

    def test_worker_starts_stack(self):
        from unittest.mock import patch

        from dashboard.models import Service
        from library.installer import SECURO_NETWORK, _install_worker
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="securo",
            container_name="cc-securo",
            status=InstalledService.Status.INSTALLING,
        )
        client = self._mock_docker()
        with patch("library.installer.get_docker_client", return_value=client), patch(
            "library.installer.pick_host_port", return_value=3030
        ), patch("library.installer.secrets.token_urlsafe", return_value="securo-secret"), patch(
            "library.installer.services_host", return_value="192.168.1.10"
        ):
            _install_worker("securo")
        runs = {row["name"]: row for row in client._runs}
        self.assertEqual(
            set(runs),
            {
                "cc-securo",
                "cc-securo-backend",
                "cc-securo-db",
                "cc-securo-redis",
                "cc-securo-worker",
                "cc-securo-beat",
            },
        )
        frontend = runs["cc-securo"]
        backend = runs["cc-securo-backend"]
        self.assertEqual(frontend["network"], SECURO_NETWORK)
        self.assertEqual(frontend["ports"], {"8080/tcp": 3030})
        self.assertEqual(frontend["environment"]["BACKEND_URL"], "http://cc-securo-backend:8000")
        self.assertEqual(frontend["environment"]["FRONTEND_URL"], "http://192.168.1.10:3030")
        self.assertEqual(backend["network"], SECURO_NETWORK)
        self.assertEqual(backend["extra_hosts"]["host.docker.internal"], "host-gateway")
        self.assertIn("securo-secret", backend["environment"]["DATABASE_URL"])
        self.assertEqual(backend["environment"]["FRONTEND_URL"], "http://192.168.1.10:3030")
        self.assertEqual(runs["cc-securo-db"]["labels"]["control-center.role"], "db")
        self.assertEqual(runs["cc-securo-db"]["environment"]["POSTGRES_PASSWORD"], "securo-secret")
        row = InstalledService.objects.get(slug="securo")
        self.assertEqual(row.status, InstalledService.Status.RUNNING)
        self.assertTrue(Service.objects.filter(catalog_slug="securo").exists())

    def test_uninstall_removes_sidecars_and_network(self):
        from unittest.mock import MagicMock, patch

        from library.installer import uninstall
        from library.models import InstalledService

        InstalledService.objects.create(
            slug="securo",
            container_name="cc-securo",
            host_port=3030,
            status=InstalledService.Status.RUNNING,
        )
        create_dashboard_card("securo", get_service_by_slug("securo"), 3030)
        client = MagicMock()
        client.volumes.list.return_value = []
        client.containers.list.return_value = []
        net = MagicMock()
        client.networks.get.return_value = net
        with patch("library.installer.get_docker_client", return_value=client):
            ok, message = uninstall("securo", remove_data=True)
        self.assertTrue(ok)
        names = [call.args[0] for call in client.containers.get.call_args_list]
        self.assertIn("cc-securo", names)
        self.assertIn("cc-securo-db", names)
        self.assertIn("cc-securo-backend", names)
        self.assertIn("cc-securo-redis", names)
        client.networks.get.assert_called_with("cc-securo-net")
        net.remove.assert_called()
        self.assertEqual(message, "Uninstalled")


class DebugPortReconcileTests(TestCase):
    def test_detect_imports_get_docker_spec(self):
        import library.detect as detect
        from library.catalog import get_docker_spec

        self.assertIs(detect.get_docker_spec, get_docker_spec)

    def test_apply_address_sync_preserves_custom_widget_url(self):
        from dashboard.models import Service, ServiceCategory
        from library.debug_ports import AddressSnapshot, apply_address_sync
        from library.models import InstalledService

        cat = ServiceCategory.objects.create(name="Apps")
        service = Service.objects.create(
            category=cat,
            name="Jellyfin",
            host="192.168.0.40",
            port=8096,
            path="/",
            href="http://192.168.0.40:8096/",
            catalog_slug="jellyfin",
            enabled=True,
        )
        Service.objects.filter(pk=service.pk).update(
            widget_url="https://metrics.example.com/api",
            href="http://192.168.0.40:8096/",
            health_check_url="http://192.168.0.40:8096/",
        )
        service.refresh_from_db()
        InstalledService.objects.create(
            slug="jellyfin",
            container_name="cc-jellyfin",
            host_port=8096,
            status=InstalledService.Status.RUNNING,
        )
        snap = AddressSnapshot(
            host="192.168.0.40",
            port=9096,
            source="docker",
            confidence="high",
        )
        result = apply_address_sync(service, snap, update_kuma=False, update_tunnel=False)
        service.refresh_from_db()
        self.assertTrue(result.ok)
        self.assertEqual(service.port, 9096)
        self.assertEqual(service.href, "http://192.168.0.40:9096/")
        self.assertEqual(service.widget_url, "https://metrics.example.com/api")
        self.assertEqual(
            InstalledService.objects.get(slug="jellyfin").host_port,
            9096,
        )

    def test_ingress_origin_keeps_non_default_port_on_public_host(self):
        from core.models import SiteSettings
        from library.cloudflare import ingress_origin

        site = SiteSettings.load()
        site.cf_zone_name = "thezaidan.family"
        site.services_host = "192.168.0.40"
        site.save()
        self.assertEqual(
            ingress_origin(
                "http://jellyfin.thezaidan.family:9999/",
                catalog_slug="jellyfin",
            ),
            "http://192.168.0.40:9999",
        )
        self.assertNotEqual(
            ingress_origin(
                "http://jellyfin.thezaidan.family:9999/",
                catalog_slug="jellyfin",
            ),
            "http://192.168.0.40:8096",
        )
