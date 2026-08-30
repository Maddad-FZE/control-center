import os
import sys
import tarfile
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core import updates
from core.models import UpdateStatus


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


class FakeStatus:
    def __init__(self):
        self.install_step = ""
        self.install_step_index = 0
        self.install_total_steps = 0
        self.install_log = ""
        self.saves = 0

    def save(self, update_fields=None):
        self.saves += 1


class RunStepTests(SimpleTestCase):
    def test_streams_output_into_log(self):
        log = []
        status = FakeStatus()
        ok = updates._run_step(
            "Echo",
            [sys.executable, "-c", "print('line-one'); print('line-two')"],
            log,
            cwd=".",
            timeout=10,
            status=status,
            step_index=4,
        )
        self.assertTrue(ok)
        joined = "\n".join(log)
        self.assertIn("line-one", joined)
        self.assertIn("line-two", joined)
        self.assertGreaterEqual(status.saves, 1)

    def test_nonzero_exit_is_failure(self):
        log = []
        ok = updates._run_step(
            "Fail",
            [sys.executable, "-c", "raise SystemExit(3)"],
            log,
            cwd=".",
            timeout=10,
        )
        self.assertFalse(ok)
        self.assertTrue(any("exit code 3" in row for row in log))


class RestartTests(SimpleTestCase):
    def test_missing_restart_binary_falls_back(self):
        log = []
        with self.settings(UPDATE_RESTART_COMMAND="definitely-not-a-cc-binary restart"):
            with patch.object(updates, "_find_gunicorn_master", return_value=None):
                ok = updates._restart_application(log)
        self.assertFalse(ok)
        self.assertTrue(any("not available" in row for row in log))

    def test_empty_command_does_not_invoke_docker(self):
        log = []
        with self.settings(UPDATE_RESTART_COMMAND=""):
            with patch.object(updates, "_find_gunicorn_master", return_value=None):
                with patch.object(updates.subprocess, "Popen") as popen:
                    updates._restart_application(log)
        popen.assert_not_called()
        self.assertTrue(any("manually" in row.lower() for row in log))

    def test_sighup_when_gunicorn_master_found(self):
        log = []
        with self.settings(UPDATE_RESTART_COMMAND=""):
            with patch.object(updates, "_find_gunicorn_master", return_value=4242):
                with patch.object(updates.os, "kill") as kill:
                    ok = updates._restart_application(log)
        self.assertTrue(ok)
        kill.assert_called_once()
        self.assertEqual(kill.call_args[0][0], 4242)


class EphemeralAppDirTests(SimpleTestCase):
    def test_host_is_not_ephemeral(self):
        self.assertFalse(updates.app_dir_is_ephemeral("/app", in_docker=False, mountinfo=""))

    def test_docker_without_app_bind_is_ephemeral(self):
        mountinfo = "123 1 8:1 / / rw - overlay overlay rw\n456 123 8:1 / /app/data rw - ext4 /dev/sda1 rw\n"
        self.assertTrue(
            updates.app_dir_is_ephemeral("/app", in_docker=True, mountinfo=mountinfo)
        )

    def test_docker_with_app_bind_is_durable(self):
        mountinfo = "123 1 8:1 / / rw - overlay overlay rw\n456 123 8:1 /home/pi/app /app rw - ext4 /dev/sda1 rw\n"
        self.assertFalse(
            updates.app_dir_is_ephemeral("/app", in_docker=True, mountinfo=mountinfo)
        )


class RecoverInstallTests(TestCase):
    def test_marks_dead_running_install_failed(self):
        status = UpdateStatus.load()
        status.install_state = UpdateStatus.InstallState.RUNNING
        status.install_started_at = timezone.now() - timedelta(minutes=5)
        status.install_log = "stuck at Dependencies"
        status.save()
        lock = Path(settings.BASE_DIR) / "data" / "update-install.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999", encoding="utf-8")
        try:
            self.assertTrue(updates.recover_stale_install())
            status.refresh_from_db()
            self.assertEqual(status.install_state, UpdateStatus.InstallState.FAILED)
            self.assertIn("stopped before it finished", status.install_log)
            self.assertFalse(lock.exists())
        finally:
            lock.unlink(missing_ok=True)

    def test_leaves_live_lock_alone(self):
        status = UpdateStatus.load()
        status.install_state = UpdateStatus.InstallState.RUNNING
        status.install_started_at = timezone.now()
        status.save()
        lock = Path(settings.BASE_DIR) / "data" / "update-install.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()), encoding="utf-8")
        try:
            self.assertFalse(updates.recover_stale_install())
            status.refresh_from_db()
            self.assertEqual(status.install_state, UpdateStatus.InstallState.RUNNING)
        finally:
            lock.unlink(missing_ok=True)


class StartInstallTests(TestCase):
    def test_spawns_install_update_command(self):
        status = UpdateStatus.load()
        status.latest_version = "v9.9.9"
        status.install_state = UpdateStatus.InstallState.IDLE
        status.save()
        fake = MagicMock()
        fake.pid = 4321
        with self.settings(UPDATES_ALLOW_INSTALL=True):
            with patch.object(updates.subprocess, "Popen", return_value=fake) as popen:
                started, message = updates.start_install("v9.9.9", "admin")
        self.assertTrue(started)
        self.assertIn("v9.9.9", message)
        args = popen.call_args[0][0]
        self.assertIn("install_update", args)
        self.assertIn("v9.9.9", args)
        lock = Path(settings.BASE_DIR) / "data" / "update-install.lock"
        try:
            self.assertEqual(lock.read_text(encoding="utf-8").strip(), "4321")
        finally:
            lock.unlink(missing_ok=True)
            cache.delete(updates.INSTALL_LOCK_KEY)


class StaleInstallProgressTests(TestCase):
    def _status(self, **kwargs):
        status = UpdateStatus.load()
        fields = {
            "latest_version": "v0.3.1",
            "install_state": UpdateStatus.InstallState.SUCCESS,
            "install_log": "Installed 0.3.0",
            "installed_version": "0.3.0",
            "install_target_version": "v0.3.0",
            "install_step": "done",
            "install_step_index": 7,
            "restart_required": False,
        }
        fields.update(kwargs)
        for name, value in fields.items():
            setattr(status, name, value)
        status.save()
        return status

    def test_status_payload_resets_previous_success_when_newer_release_exists(self):
        self._status()
        with patch.object(updates, "get_current_version", return_value="0.3.0"):
            payload = updates.status_payload()
        self.assertEqual(payload["install_state"], "idle")
        self.assertEqual(payload["install_log"], "")
        self.assertEqual(payload["install_percent"], 0)
        self.assertTrue(payload["update_available"])
        status = UpdateStatus.load()
        self.assertEqual(status.install_state, UpdateStatus.InstallState.IDLE)
        self.assertEqual(status.install_target_version, "")

    def test_keeps_failed_state_for_the_current_latest(self):
        self._status(
            install_state=UpdateStatus.InstallState.FAILED,
            install_log="boom",
            installed_version="",
            install_target_version="v0.3.1",
        )
        with patch.object(updates, "get_current_version", return_value="0.3.0"):
            payload = updates.status_payload()
        self.assertEqual(payload["install_state"], "failed")
        self.assertEqual(payload["install_log"], "boom")

    def test_clears_failed_state_for_an_older_release(self):
        self._status(
            install_state=UpdateStatus.InstallState.FAILED,
            install_log="boom 0.3.0",
            installed_version="",
            install_target_version="v0.3.0",
        )
        with patch.object(updates, "get_current_version", return_value="0.3.0"):
            payload = updates.status_payload()
        self.assertEqual(payload["install_state"], "idle")
        self.assertEqual(payload["install_log"], "")

    def test_keeps_success_when_already_on_latest(self):
        self._status(
            latest_version="v0.3.1",
            installed_version="0.3.1",
            install_target_version="v0.3.1",
            install_log="done",
        )
        with patch.object(updates, "get_current_version", return_value="0.3.1"):
            payload = updates.status_payload()
        self.assertFalse(payload["update_available"])
        self.assertEqual(payload["install_state"], "success")
        self.assertEqual(payload["install_log"], "done")
        self.assertEqual(payload["install_percent"], 100)

    def test_does_not_clear_a_running_install(self):
        self._status(
            install_state=UpdateStatus.InstallState.RUNNING,
            install_log="Downloading",
            install_target_version="v0.3.1",
            installed_version="0.3.0",
            install_started_at=timezone.now(),
        )
        with patch.object(updates, "get_current_version", return_value="0.3.0"):
            payload = updates.status_payload()
        self.assertEqual(payload["install_state"], "running")
        self.assertEqual(payload["install_log"], "Downloading")

    def test_check_for_update_clears_old_success(self):
        self._status(latest_version="v0.3.0")
        release = {
            "tag_name": "v0.3.1",
            "html_url": "https://github.com/example/repo/releases/tag/v0.3.1",
            "body": "notes",
            "published_at": None,
        }
        with self.settings(GITHUB_REPO="example/repo"):
            with patch.object(updates, "get_current_version", return_value="0.3.0"):
                with patch.object(updates, "_fetch_latest_release", return_value=(release, "")):
                    status = updates.check_for_update()
        self.assertEqual(status.latest_version, "v0.3.1")
        self.assertEqual(status.install_state, UpdateStatus.InstallState.IDLE)
        self.assertEqual(status.install_log, "")


if __name__ == "__main__":
    unittest.main()
