# dcss-server-install

[![Latest release](https://img.shields.io/github/v/release/tarballqc/dcss-server-install?label=release)](https://github.com/tarballqc/dcss-server-install/releases)
[![License](https://img.shields.io/github/license/tarballqc/dcss-server-install)](LICENSE)
[![Discord](https://img.shields.io/badge/discord-roguelikes.gg-5865F2?logo=discord&logoColor=white)](https://discord.gg/4Wattvg5Mh)

One-command installer for an unofficial **Dungeon Crawl Stone Soup** WebTiles + SSH server. Multi-version DCSS, sound, scoring, password-reset emails, optional Discord bot, and HTTPS via Let's Encrypt — provisioned by a single bootstrap script and a guided wizard.

## Quick start

On a fresh Linux box (Debian / Ubuntu / Amazon Linux 2023 / RHEL / Fedora) with sudo, ports 80 / 443 / 222 open, and DNS pointing to the server:

```bash
curl -fsSL https://raw.githubusercontent.com/tarballqc/dcss-server-install/main/bootstrap.sh | bash
```

The bootstrap detects your distro, installs git + Docker, clones the latest release into `~/dcss`, and launches the wizard. After it finishes, run `./run.sh game` (~20-minute build), then browse to `https://your-host/`.

To inspect the bootstrap before running it: <https://raw.githubusercontent.com/tarballqc/dcss-server-install/main/bootstrap.sh>. Manual install steps are in [`docs/prereqs.md`](docs/prereqs.md).

## Features

- **DCSS 0.34 + trunk** with Tutorial, Sprint, Seeded, and Descent modes for each. Older versions (0.30–0.33) opt-in.
- **Browser play (WebTiles)** at `https://your-host/` and **SSH play (dgamelaunch)** on port 222, sharing accounts and saves.
- **DWEM sound module**, with three soundpacks loaded directly from [nemelex.cards](https://nemelex.cards) — credit and traffic to upstream maintainers.
- **Leaderboard, per-player profile pages, and server stats** at `/scores/`.
- **Styled morgue / ttyrec / rcfile browsers** at `/morgue/`, `/ttyrec/`, `/rcfiles/`.
- **Forgot Password emails** with a provider picker (AWS SES, Mailgun, SendGrid, Postmark, or custom SMTP) and an optional setup-time test send.
- **Optional Discord bot** posting wins, deaths, and milestones to a channel.
- **HTTPS via Let's Encrypt** (host nginx + certbot) wired up by the wizard.
- **Auto-detected upstream releases** with twice-daily rebuilds via cron.
- **Per-server templating** — `SERVER_ABBR`, hostname, region, admin handle in `.env` flow through every user-facing surface.

## Requirements

| | |
|---|---|
| OS | Linux with `apt`, `dnf`, or `yum` |
| RAM | 4 GB minimum, 8 GB+ recommended |
| Disk | 20 GB |
| Docker | Engine 24+ with Compose v2 (auto-installed if missing) |
| Ports | 80, 443, 222 publicly accessible |
| DNS | A record pointing at the server before TLS provisioning |

Optional: SMTP credentials for password reset, a Discord bot token.

## Documentation

| | |
|---|---|
| [Prerequisites](docs/prereqs.md) | OS, RAM, ports, DNS, Docker plugins |
| [Customizing](docs/customizing.md) | Banner, theme, MOTD, default RC, game modes |
| [SSH play](docs/ssh-play.md) | dgamelaunch, default password, key auth |
| [Password reset](docs/password-reset.md) | SMTP setup, STARTTLS, email template |
| [Multi-server](docs/multi-server.md) | Templating pattern for running multiple servers |
| [Discord bot](docs/discord-bot.md) | Bot token, intents, channel config |
| [Upgrading](docs/upgrading.md) | Auto-rebuild cron, manual upgrades, frozen versions |
| [Troubleshooting](docs/troubleshooting.md) | Common gotchas |

## Deploy modes

`./run.sh <mode>` wraps `bash scripts/deploy.sh <mode>`:

| Mode | Use when | Time |
|---|---|---|
| `game` | Full rebuild — code, binaries (default) | ~20 min |
| `banner` | Anything in `config/` changed (banner, theme, RC, dgamelaunch) | ~5 sec |
| `scoring` | `scoring/generate_scores.py` changed | ~10 sec |
| `web` | nginx config changed | ~2 sec |
| `config` | `webtiles.py` or `games.d/` changed | ~5 sec |

## Scope

This repo helps you run an **unofficial** DCSS server — community, private, friends-only, or dev/test. It is *not* a path to becoming an [official DCSS server](https://crawl.develz.org/); those are reviewed and approved by the DCSS dev team in `##crawl-dev` on Libera IRC. What this *can* do is give a prospective official-server admin something concrete to learn on.

## Support

| | |
|---|---|
| Bugs, feature requests | [GitHub Issues](https://github.com/tarballqc/dcss-server-install/issues) |
| Usage questions, sharing setups | [GitHub Discussions](https://github.com/tarballqc/dcss-server-install/discussions) |
| Real-time chat | [Discord](https://discord.gg/4Wattvg5Mh) — `@tarballqc` |
| Security disclosures | <tarballqc@roguelikes.gg> |

## Contributing

Pull requests welcome. The bar:

- Open an issue first for non-trivial changes.
- Test on a fresh Linux VM end-to-end (`./install.sh` + `./run.sh game`).
- Keep server-specific identity behind `__SERVER_*__` placeholders so multi-server admins keep working.
- Update [`CHANGELOG.md`](CHANGELOG.md) under `[Unreleased]`. SemVer applies to releases.
- Credit upstream when adding external dependencies.

Pin to a specific release for stability:

```bash
git clone --branch v1.0.7 https://github.com/tarballqc/dcss-server-install ~/dcss
```

## License

[MIT](LICENSE). DCSS itself is GPL-3 and is fetched from upstream at build time, not redistributed in this repo.

## Credits

- The [Dungeon Crawl Stone Soup](https://crawl.develz.org/) team for the game.
- [refracta](https://github.com/refracta/dcss-webtiles-extension-module) for the DWEM extension module.
- [nemelex.cards](https://nemelex.cards) for the [OSP](https://osp.nemelex.cards/), [BindTheEarth](https://sound-packs.nemelex.cards/Autofire/BindTheEarth/), and [DCSS-UST](https://sound-packs.nemelex.cards/DCSS-UST/) soundpacks.
- [dgamelaunch](https://github.com/paxed/dgamelaunch) for the SSH game launcher.

Built and maintained by [tarballqc](https://github.com/tarballqc) — admin of [crawl.roguelikes.gg](https://crawl.roguelikes.gg) (CRG) and [crawl-br.roguelikes.gg](https://crawl-br.roguelikes.gg) (CBRG).
