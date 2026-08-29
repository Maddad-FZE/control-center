# Changelog

All notable changes to the Homelab Control Center are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-29

### Added

- Header update chip to the left of weather; it appears only when a release is available and shakes every 7 seconds

### Changed

- In-app updates download the GitHub release archive instead of requiring a git checkout
- Install keeps `data/`, `.env`, and `media/` in place, then migrates and restarts

## [0.1.2] - 2026-08-29

### Added

- Optional Merlin wizard with page tips and spoken site messages
- Site settings to call in the wizard and let him notify instead of toasts
- Misc chips with edit, visibility, and delete (bookmarks migrate to services)
- Weather and clock in the header for guests, using the server timezone
- Clickable Up filter (`is:up`) alongside Down
- Red status lights flash while a health check is in progress

### Changed

- Down cards fade instead of using a hazard stripe
- Misc kebab sits beside the icon and stays vertically centered
- Weather API is public so guests see the same site location

## [0.1.1] - 2026-08-29

### Added

- One-click update popup with live progress bar, step checklist, and install log
- `manage.py bump_version` to roll VERSION and CHANGELOG for a release
- Library install popup with indeterminate progress while Docker pulls
- Card URLs prefer the LAN host used to open the site (not Docker bridge IPs)
- Full-page card editor with service search/dropdown, icon library, live-stats column, and footer save
- Guest status bar, site title/tagline settings, toast notifications, and public branding files
- Versioned CSS/JS so the UI stays fast without flashing stale designs

## [0.1.0] - 2026-08-28

### Added

- Retro wood/orange dashboard with live service health checks and widgets
- Guest, user, and admin roles with public/private service cards
- In-app card management (add, edit, delete, visibility) for admins
- First-run setup wizard
- Settings screen with appearance, site branding, users, and platform sections
- Version reporting, GitHub release checks every 12 hours, and in-app updates
