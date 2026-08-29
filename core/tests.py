import tarfile
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from core import updates


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_release_tree(root, version="0.9.9"):
    _write(root / "VERSION", f"{version}\n")
    _write(root / "requirements.txt", "django\n")
    _write(root / "core" / "app.py", "NEW = 1\n")
    _write(root / "core" / "keep.py", "kept\n")
    _write(root / "templates" / "home.html", "<p>new</p>\n")


class ArchiveUrlTests(SimpleTestCase):
    def test_builds_github_tag_url(self):
        self.assertEqual(
            updates.archive_url("Maddad-FZE/control-center", "v0.1.3"),
            "https://github.com/Maddad-FZE/control-center/archive/refs/tags/v0.1.3.tar.gz",
        )

    def test_rejects_bad_repo(self):
        with self.assertRaises(ValueError):
            updates.archive_url("https://evil.example/repo", "v0.1.3")


class ApplyReleaseTests(SimpleTestCase):
    def test_overlays_app_files_and_preserves_local_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dest = Path(tmp) / "dest"
            _build_release_tree(src, "0.9.9")
            _write(dest / "VERSION", "0.1.1\n")
            _write(dest / "core" / "app.py", "OLD = 1\n")
            _write(dest / "core" / "gone.py", "remove me\n")
            _write(dest / "data" / "db.sqlite3", "db")
            _write(dest / ".env", "SECRET=keep\n")
            _write(dest / "media" / "logo.png", "png")
            log = []
            updates.apply_release_tree(src, dest, log)
            self.assertEqual((dest / "VERSION").read_text(encoding="utf-8"), "0.9.9\n")
            self.assertEqual((dest / "core" / "app.py").read_text(encoding="utf-8"), "NEW = 1\n")
            self.assertFalse((dest / "core" / "gone.py").exists())
            self.assertEqual((dest / "data" / "db.sqlite3").read_text(encoding="utf-8"), "db")
            self.assertEqual((dest / ".env").read_text(encoding="utf-8"), "SECRET=keep\n")
            self.assertEqual((dest / "media" / "logo.png").read_text(encoding="utf-8"), "png")
            self.assertEqual(updates.verify_installed_version(dest, "v0.9.9"), "0.9.9")

    def test_version_mismatch_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            _write(dest / "VERSION", "0.1.0\n")
            with self.assertRaises(ValueError):
                updates.verify_installed_version(dest, "v0.9.9")


class ExtractArchiveTests(SimpleTestCase):
    def test_extracts_single_project_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            project = tmp / "pack" / "owner-repo-abc123"
            _build_release_tree(project, "1.2.3")
            archive = tmp / "release.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(project, arcname="owner-repo-abc123")
            extracted = updates.extract_release_tarball(archive, tmp / "out")
            self.assertEqual(extracted.name, "owner-repo-abc123")
            self.assertEqual((extracted / "VERSION").read_text(encoding="utf-8").strip(), "1.2.3")

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "evil.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo(name="../escape.txt")
                data = b"nope"
                info.size = len(data)
                tar.addfile(info, fileobj=__import__("io").BytesIO(data))
            with self.assertRaises(ValueError):
                updates.extract_release_tarball(archive, tmp / "out")


if __name__ == "__main__":
    unittest.main()
