from pathlib import Path

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from library.catalog import SERVICES, get_docker_spec, get_service_by_slug
from library.installer import create_dashboard_card


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
        source = Path(__file__).resolve().parents[1] / "library" / "installer.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn('if slug != "uptime-kuma":', text)
        self.assertIn("create_dashboard_card(slug, entry, host_port)", text)

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
