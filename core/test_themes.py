import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core.models import SiteSettings
from core.themes.loaders import ThemeCachedLoader
from core.themes.middleware import reset_active_theme, set_active_theme
from core.themes.registry import clear_theme_cache, get_packs, resolve_theme
from core.updates import apply_release_tree


class ThemeRegistryTests(TestCase):
    def setUp(self):
        clear_theme_cache()

    def test_bundled_packs_load(self):
        packs = get_packs()
        self.assertIn("wood", packs)
        self.assertIn("slate", packs)
        self.assertIn("glass", packs)
        self.assertEqual(packs["slate"].extends, "wood")
        self.assertEqual(packs["slate"].chain[1].slug, "wood")

    def test_unknown_default_falls_back_to_wood(self):
        site = SiteSettings.load()
        site.default_theme = "missing"
        site.save()
        from core.site_settings import clear_site_settings_cache

        clear_site_settings_cache()
        self.assertEqual(resolve_theme(None).slug, "wood")

    def test_symlink_pack_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real"
            real.mkdir()
            (real / "theme.json").write_text(
                '{"schema":1,"slug":"real","name":"Real"}', encoding="utf-8"
            )
            link_root = root / "linked"
            link_root.mkdir()
            (link_root / "real").symlink_to(real, target_is_directory=True)
            with override_settings(THEME_DIRS=[link_root]):
                clear_theme_cache()
                self.assertNotIn("real", get_packs())
            clear_theme_cache()


class ThemePreviewTests(TestCase):
    def setUp(self):
        clear_theme_cache()
        self.admin = User.objects.create_superuser("boss", "", "NewSecret123!")
        self.member = User.objects.create_user("sam", password="NewSecret123!")

    def test_preview_is_session_local(self):
        self.client.force_login(self.admin)
        resp = self.client.get("/?theme=slate")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-theme="slate"')
        other = self.client_class()
        other.force_login(self.member)
        resp = other.get("/")
        self.assertContains(resp, 'data-theme="wood"')

    def test_member_cannot_apply_theme(self):
        self.client.force_login(self.member)
        resp = self.client.post("/settings/", {"form": "appearance", "theme": "slate", "action": "apply"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(SiteSettings.load().default_theme, "wood")

    def test_admin_apply_sets_site_default(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            "/settings/",
            {"form": "appearance", "theme": "terminal", "action": "apply", "section": "appearance"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(SiteSettings.load().default_theme, "terminal")


class ThemeLoaderTests(TestCase):
    def test_cache_key_includes_slug(self):
        wood = get_packs()["wood"]
        slate = get_packs()["slate"]
        loader = ThemeCachedLoader.__new__(ThemeCachedLoader)
        token = set_active_theme(wood)
        try:
            wood_key = ThemeCachedLoader.cache_key(loader, "core/base.html")
        finally:
            reset_active_theme(token)
        token = set_active_theme(slate)
        try:
            slate_key = ThemeCachedLoader.cache_key(loader, "core/base.html")
        finally:
            reset_active_theme(token)
        self.assertNotEqual(wood_key, slate_key)
        self.assertTrue(wood_key.startswith("wood-"))


class ThemeUpdateTests(TestCase):
    def test_release_apply_keeps_data_themes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "app"
            data_theme = dest / "data" / "themes" / "custom"
            data_theme.mkdir(parents=True)
            (data_theme / "theme.json").write_text("{}", encoding="utf-8")
            src = root / "src"
            (src / "themes").mkdir(parents=True)
            (src / "themes" / "wood").mkdir()
            (src / "README.md").write_text("x", encoding="utf-8")
            apply_release_tree(src, dest, [])
            self.assertTrue((data_theme / "theme.json").is_file())


class ThemeRenderTests(TestCase):
    def test_each_pack_renders_dashboard(self):
        User.objects.create_superuser("boss", "", "NewSecret123!")
        self.client.force_login(User.objects.get(username="boss"))
        for slug in get_packs():
            resp = self.client.get(f"/?theme={slug}")
            self.assertEqual(resp.status_code, 200, slug)
            self.assertContains(resp, f'data-theme="{slug}"')
            self.assertContains(resp, "data-helper-dock-pref=")
        from core.models import SiteSettings
        from core.site_settings import clear_site_settings_cache

        site = SiteSettings.load()
        site.wizard_enabled = True
        site.save()
        clear_site_settings_cache()
        resp = self.client.get("/?theme=wood")
        body = resp.content.decode()
        body_tag = body.split(">", 1)[0]
        self.assertNotIn("data-helper-dock=", body_tag)
        self.assertEqual(body.count('id="dashboard-merlin"'), 1)
        self.assertIn('id="dashboard-merlin"', body)
        self.assertIn("data-helper-dock=", body.split("id=\"dashboard-merlin\"", 1)[1][:80])
