#!/usr/bin/env bash
# bootstrap.sh — one-command install for dcss-server-install.
#
# Usage (paste into a fresh Linux box):
#
#   curl -fsSL https://raw.githubusercontent.com/tarballqc/dcss-server-install/main/bootstrap.sh | bash
#
# What it does (in order):
#
#   1. Detect your distro  (Amazon Linux 2023, Debian, Ubuntu, RHEL, Fedora, …)
#   2. Install git + Docker via your package manager (uses sudo internally)
#   3. Start and enable the Docker daemon
#   4. Add the current user to the `docker` group
#   5. Clone the latest dcss-server-install release into  ~/dcss
#   6. Hand off to  ./install.sh  (the interactive wizard)
#
# Override the defaults with env vars before piping:
#
#   DCSS_DIR=/opt/dcss   DCSS_REF=v1.0.0   curl … | bash
#   DCSS_REPO=https://github.com/<fork>/dcss-server-install   curl … | bash
#
# This script uses sudo internally — do NOT run it as root.

set -euo pipefail

DCSS_REPO="${DCSS_REPO:-https://github.com/tarballqc/dcss-server-install}"
DCSS_DIR="${DCSS_DIR:-$HOME/dcss}"

# ── helpers ────────────────────────────────────────────────────────────────
say()  { printf "\033[1m[bootstrap]\033[0m %s\n" "$*"; }
warn() { printf "\033[33m[bootstrap]\033[0m %s\n" "$*"; }
die()  { printf "\033[31m[bootstrap]\033[0m %s\n" "$*" >&2; exit 1; }

# ── sanity ────────────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] && die "don't run this as root. It uses sudo internally where needed."
command -v sudo >/dev/null 2>&1 || die "sudo not found. Install sudo (or use a user with sudo access)."

# ── header ────────────────────────────────────────────────────────────────
cat <<'BANNER'

   ##############################################################
   #....@.....(...../...)).....D........[?]....<..........$....#
   #############################+################################

       D C S S   S E R V E R   I N S T A L L  —  B O O T S T R A P

   This will install git + Docker (with sudo), clone the latest release
   to ~/dcss, then launch the interactive setup wizard.

   By tarballqc — CRG · CBRG admin · tarballqc@roguelikes.gg
   Discord  https://discord.gg/4Wattvg5Mh   ·  @tarballqc

BANNER

# ── detect OS ─────────────────────────────────────────────────────────────
. /etc/os-release 2>/dev/null || die "/etc/os-release missing; can't detect distro."
ID="${ID:-unknown}"; ID_LIKE="${ID_LIKE:-}"
say "detected distro: $ID${ID_LIKE:+ (like $ID_LIKE)}"

# ── install git + docker ──────────────────────────────────────────────────
install_dnf() {
    say "installing git + docker via dnf …"
    sudo dnf install -y git docker
}
install_apt() {
    say "installing git + curl via apt …"
    sudo apt-get update -qq
    sudo apt-get install -y git curl ca-certificates
    if ! command -v docker >/dev/null 2>&1; then
        say "installing docker via get.docker.com …"
        curl -fsSL https://get.docker.com | sudo sh
    fi
}

case "$ID" in
    amzn|fedora|rhel|centos|rocky|almalinux)            install_dnf ;;
    debian|ubuntu|raspbian|linuxmint|pop|elementary)    install_apt ;;
    *)
        if   [[ "$ID_LIKE" =~ debian ]]; then install_apt
        elif [[ "$ID_LIKE" =~ (rhel|fedora) ]]; then install_dnf
        else
            warn "unsupported distro: $ID"
            warn "install git + docker manually, then run:"
            warn "  git clone $DCSS_REPO $DCSS_DIR && cd $DCSS_DIR && ./install.sh"
            exit 1
        fi
        ;;
esac

# ── start docker daemon ───────────────────────────────────────────────────
say "enabling + starting docker daemon …"
sudo systemctl enable --now docker

# ── docker group membership ───────────────────────────────────────────────
if ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
    say "adding $USER to the docker group …"
    sudo usermod -aG docker "$USER"
fi

# ── pick a ref to clone ───────────────────────────────────────────────────
if [ -z "${DCSS_REF:-}" ]; then
    REPO_PATH="${DCSS_REPO#https://github.com/}"
    REPO_PATH="${REPO_PATH%.git}"
    DCSS_REF="$(curl -fsSL "https://api.github.com/repos/${REPO_PATH}/releases/latest" 2>/dev/null \
                | grep -o '"tag_name": *"[^"]*"' | head -1 | cut -d'"' -f4 || true)"
    DCSS_REF="${DCSS_REF:-main}"
fi
say "using release: $DCSS_REF"

# ── clone or update repo ──────────────────────────────────────────────────
if [ -d "$DCSS_DIR/.git" ]; then
    say "$DCSS_DIR exists; fetching $DCSS_REF …"
    git -C "$DCSS_DIR" fetch --tags --quiet
    git -C "$DCSS_DIR" checkout --quiet "$DCSS_REF"
else
    say "cloning $DCSS_REPO@$DCSS_REF → $DCSS_DIR"
    git clone --quiet --branch "$DCSS_REF" "$DCSS_REPO" "$DCSS_DIR"
fi

cd "$DCSS_DIR"

# ── hand off to wizard ────────────────────────────────────────────────────
echo
say "prereqs ready. Launching install.sh …"
echo

# Test docker access from this shell. If we just added ourselves to the docker
# group, the running process doesn't have it active yet — fall through to
# `sg docker` to activate it without forcing a re-login.
if docker info >/dev/null 2>&1; then
    exec bash "$DCSS_DIR/install.sh" </dev/tty
elif command -v sg >/dev/null 2>&1; then
    exec sg docker -c "exec bash '$DCSS_DIR/install.sh' </dev/tty"
else
    echo
    warn "Docker daemon access requires a fresh shell (group change pending)."
    warn "Log out + log back in, then run:"
    warn "  cd $DCSS_DIR && ./install.sh"
fi
