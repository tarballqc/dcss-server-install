# Changelog

All notable changes to dcss-server-install. Versioning follows [SemVer](https://semver.org/).

- **MAJOR** — breaking changes (admins need to migrate)
- **MINOR** — new features, backward compatible
- **PATCH** — bug fixes only

## [Unreleased]

## [1.0.0] — 2026-04-28

Initial public release. One-command installer for an unofficial DCSS WebTiles + SSH server, validated end-to-end on Amazon Linux 2023 and Ubuntu 24.04 LTS.

### Install path

- **`bootstrap.sh`** — single `curl … | bash` entry point. Detects the distro (AL2023 / Debian / Ubuntu / RHEL / Fedora), installs git + Docker via the native package manager, starts the daemon, adds the user to the `docker` group, clones the latest release into `~/dcss`, and hands off to the wizard with a working TTY.
- **`install.sh`** — interactive setup wizard. Numbered section headers, BBS-style status prefixes, DCSS-themed banner. Collects server identity, SMTP (provider picker for AWS SES / Mailgun / SendGrid / Postmark / custom), optional Discord bot, imported-account hint, older-version build flag, and host nginx + certbot HTTPS. Self-installs Docker Compose v2 and buildx if missing or below the version `docker compose build` requires.
- **`run.sh`** — wraps `scripts/deploy.sh` for the post-install build and ongoing operations.

### Server features

- **DCSS 0.34 + trunk** with Tutorial, Sprint, Seeded, and Descent modes for each. Older versions (0.30–0.33) opt-in via `Dockerfile.game.full` and `scripts/build-frozen.sh`.
- **Browser play (WebTiles)** at `https://your-host/` and **SSH play (dgamelaunch)** on port 222, sharing accounts and saves.
- **DWEM sound module** with three popular soundpacks loaded directly from upstream maintainers at [nemelex.cards](https://nemelex.cards) — no local hosting, full credit to authors.
- **Leaderboard, per-player profile pages, and server stats** at `/scores/`.
- **Styled morgue / ttyrec / rcfile browsers** at `/morgue/`, `/ttyrec/`, `/rcfiles/`.
- **Forgot Password emails** with a server-branded HTML body, STARTTLS support patched into upstream WebTiles, and an optional setup-time test send.
- **Optional Discord bot** (compose profile) for win/death/milestone announcements.
- **HTTPS via Let's Encrypt** through host nginx + certbot, set up by the wizard.
- **Auto-detected upstream releases** with a twice-daily rebuild cron.
- **Major-version freezing** via `scripts/upgrade-stable.sh`.
- **Empty-state-friendly `/meta/<version>/{logfile,milestones}` endpoints** so external aggregators (sequell, dcss-stats) don't 404 on a brand-new server.

### Per-server templating

`SERVER_ABBR`, `SERVER_URL`, `SERVER_HOST`, and `SERVER_ADMIN` flow through every user-facing surface — lobby banner, dgamelaunch SSH menus, scoring HTML, browse pages, code of conduct, password-reset email body — via `__SERVER_*__` placeholders substituted at deploy and startup from `.env`. Run any number of servers from one repo with one config file each.

### Documentation

`docs/{prereqs,customizing,ssh-play,password-reset,multi-server,discord-bot,upgrading,troubleshooting}.md`.

### License

MIT.

[Unreleased]: https://github.com/tarballqc/dcss-server-install/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/tarballqc/dcss-server-install/releases/tag/v1.0.0
