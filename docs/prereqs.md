# Prerequisites

## Hardware

| Player count | Recommended box |
|---|---|
| ≤10 concurrent | 2 vCPU / 4 GB RAM |
| ≤30 concurrent | 2 vCPU / 8 GB RAM |
| ≤60 concurrent | 4 vCPU / 16 GB RAM |
| 60+ | profile and scale up |

Each in-game player ≈ 50–100 MB resident. CPU is rarely the bottleneck — DCSS mostly waits for input. RAM is the hard limit.

Disk: 20 GB minimum (Docker images + a few months of morgues/ttyrecs). Older-version opt-in adds ~5 GB.

## OS

Tested on **Ubuntu 22.04+**, **Debian 12+**, **Amazon Linux 2023**. Anything with Docker Engine 24+ and `apt`/`dnf`/`yum` should work. Other distros: install Docker manually and skip the certbot step in `install.sh` (set up TLS yourself).

## Ports

| Port | What | Source |
|---|---|---|
| **80** | HTTP (redirects to HTTPS via certbot) | public |
| **443** | HTTPS (host nginx → docker) | public |
| **222** | SSH play (dgamelaunch) | public |
| 8080 | WebTiles (in container) | internal only |
| 8880 | docker nginx (host loopback) | 127.0.0.1 only |

Open 80/443/222 inbound on your firewall / security group.

## DNS

Point an A record from your hostname (the one you'll give the wizard) to your server's public IP **before** running certbot, otherwise the cert request will fail.

## Base packages (git + curl)

Most distros ship these, but a fresh **Amazon Linux 2023** install does *not* include `git`. AL2023 *does* ship `curl-minimal` which provides the `curl` binary — don't install full `curl` over it (you'll hit a `curl-minimal` vs `curl` conflict). Install just what's missing:

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y git curl

# Amazon Linux 2023 / RHEL / Fedora
sudo dnf install -y git
# (curl-minimal is already installed and is sufficient)
```

## Docker

```bash
# Debian/Ubuntu
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"; newgrp docker

# Amazon Linux 2023
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user; newgrp docker
```

**Note: Compose v2 + buildx plugins.** Amazon Linux 2023's `docker` package does *not* include the Compose v2 plugin, and ships an older buildx (~0.11) that `docker compose build` (Compose v2.30+) refuses to use. `install.sh` detects both on first run and offers to install the upstream binaries automatically (`/usr/local/lib/docker/cli-plugins/`). If you'd rather pre-install them manually:

```bash
ARCH="$(uname -m)"   # x86_64 or aarch64
sudo mkdir -p /usr/local/lib/docker/cli-plugins

# Compose v2
sudo curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# buildx (>= 0.17.0 required by Compose v2.30+)
BX_ARCH=amd64; [ "$ARCH" = aarch64 ] && BX_ARCH=arm64
BX_TAG=$(curl -fsSL https://api.github.com/repos/docker/buildx/releases/latest | grep tag_name | cut -d'"' -f4)
sudo curl -fsSL "https://github.com/docker/buildx/releases/download/${BX_TAG}/buildx-${BX_TAG}.linux-${BX_ARCH}" \
    -o /usr/local/lib/docker/cli-plugins/docker-buildx
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx
```

The Debian/Ubuntu `get.docker.com` script installs both plugins for you, so this only matters on AL2023 / RHEL-family.

Verify:

```bash
docker version
docker compose version    # must be Compose v2
```

## SMTP (optional, for Forgot Password)

Any STARTTLS-capable SMTP provider on port 587. Tested with **AWS SES** (`email-smtp.<region>.amazonaws.com`). Mailgun, SendGrid, Postmark, your own postfix all work.

You'll need:
- Host (e.g. `email-smtp.us-east-1.amazonaws.com`)
- Username + password
- A verified "From" address

If you skip SMTP at install time, password-reset will be disabled — players can still register and log in. Add credentials to `.env` later and `./run.sh banner` to enable.

## Discord bot (optional)

Create an application at https://discord.com/developers/applications, add a bot, copy the token. Required intents: **Server Members** and **Message Content** (see `docs/discord-bot.md`). You'll also need the **Guild ID** and **Channel ID** for the announcements channel.
