"""Bump VERSION and roll CHANGELOG.md Unreleased into a dated version heading."""

import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.version import VERSION_FILE, clear_version_cache, get_current_version

CHANGELOG_PATH = Path(settings.BASE_DIR) / "CHANGELOG.md"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
UNRELEASED = "## [Unreleased]"


def _parse(version):
    parts = version.strip().lstrip("vV").split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise CommandError(f"VERSION is not X.Y.Z: {version}")
    return [int(p) for p in parts]


def next_version(current, kind):
    major, minor, patch = _parse(current)
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def update_changelog(text, version, today):
    heading = f"## [{version}] - {today}"
    if UNRELEASED not in text:
        raise CommandError("CHANGELOG.md is missing an ## [Unreleased] heading.")
    if f"## [{version}]" in text:
        raise CommandError(f"CHANGELOG.md already has a heading for {version}.")
    replacement = f"{UNRELEASED}\n\n{heading}"
    return text.replace(UNRELEASED, replacement, 1)


class Command(BaseCommand):
    help = "Bump VERSION, roll CHANGELOG Unreleased into a dated heading, and print git tag commands."

    def add_arguments(self, parser):
        parser.add_argument(
            "part",
            nargs="?",
            choices=["patch", "minor", "major"],
            help="Which semver component to increment.",
        )
        parser.add_argument("--set", dest="set_version", help="Set an explicit X.Y.Z version.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the intended changes without writing files.",
        )

    def handle(self, *args, **options):
        current = get_current_version()
        set_version = options.get("set_version")
        part = options.get("part")
        if set_version:
            if not SEMVER.match(set_version):
                raise CommandError("--set requires X.Y.Z")
            new_version = set_version
        elif part:
            new_version = next_version(current, part)
        else:
            raise CommandError("Specify patch, minor, major, or --set X.Y.Z")

        changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
        today = date.today().isoformat()
        new_changelog = update_changelog(changelog, new_version, today)

        self.stdout.write(f"Current: {current}")
        self.stdout.write(f"New:     {new_version}")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run — files not written."))
            self.stdout.write(f"Would write {VERSION_FILE}")
            self.stdout.write(f"Would insert {UNRELEASED} then ## [{new_version}] - {today} in CHANGELOG.md")
            return

        VERSION_FILE.write_text(f"{new_version}\n", encoding="utf-8")
        CHANGELOG_PATH.write_text(new_changelog, encoding="utf-8")
        clear_version_cache()
        tag = f"v{new_version}"
        self.stdout.write(self.style.SUCCESS(f"Bumped to {new_version}"))
        self.stdout.write("Next:")
        self.stdout.write(f"  git add VERSION CHANGELOG.md && git commit -m \"Release {tag}\"")
        self.stdout.write(f"  git tag {tag} && git push origin main --tags")
