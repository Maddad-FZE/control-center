# Changelog

All notable changes to the Homelab Control Center are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- One-click update popup with live progress bar, step checklist, and install log
- `manage.py bump_version` to roll VERSION and CHANGELOG for a release
- Library install popup with indeterminate progress while Docker pulls
- Card URLs prefer the LAN host used to open the site (not Docker bridge IPs)

## [0.1.0] - 2026-08-28

### Added

- Retro wood/orange dashboard with live service health checks and widgets
- Guest, user, and admin roles with public/private service cards
- In-app card management (add, edit, delete, visibility) for admins
- First-run setup wizard
- Settings screen with appearance, site branding, users, and platform sections
- Version reporting, GitHub release checks every 12 hours, and in-app updates
