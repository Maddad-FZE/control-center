from django.test import SimpleTestCase

from library.catalog import SERVICES, get_docker_spec, get_service_by_slug


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
