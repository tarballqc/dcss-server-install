#!/usr/bin/env bash
# install.sh — interactive setup wizard for dcss-server-install
# Writes .env, optionally configures host nginx + certbot, then prints next steps.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(cat VERSION 2>/dev/null || echo 'dev')"

# `./install.sh --version` prints version and exits, useful for support.
case "${1:-}" in
    -v|--version)  echo "dcss-server-install $VERSION"; exit 0 ;;
esac

# ── Visual helpers ─────────────────────────────────────────────────────────
bold()   { printf "\033[1m%s\033[0m" "$*"; }
green()  { printf "\033[32m%s\033[0m" "$*"; }
yellow() { printf "\033[33m%s\033[0m" "$*"; }
cyan()   { printf "\033[36m%s\033[0m" "$*"; }
dim()    { printf "\033[2m%s\033[0m" "$*"; }
red()    { printf "\033[31m%s\033[0m" "$*"; }
hr()     { printf "\033[2m%s\033[0m\n" "════════════════════════════════════════════════════════════════════════"; }
rule()   { printf "\033[2m%s\033[0m\n" "────────────────────────────────────────────────────────────────────────"; }

# BBS-style status prefixes
ok()      { printf "  %s %s\n" "$(green '[+]')"  "$*"; }
info()    { printf "  %s %s\n" "$(cyan   '[*]')" "$*"; }
note()    { printf "  %s %s\n" "$(yellow '[!]')" "$*"; }
fail()    { printf "  %s %s\n" "$(red    '[x]')" "$*"; }
working() { printf "  %s %s\n" "$(dim    '[~]')" "$*"; }

# Section divider with a numbered title and optional caption.
# Sections 01-07 are the main wizard phases; 07 is "summary".
section() {
    local num="$1" title="$2" caption="${3:-}"
    echo
    printf "   %s\n" "$(cyan "════════════════════════════════════════════════════════════════════════")"
    printf "      %s   %s\n" "$(bold "[$num / 07]")" "$(bold "$title")"
    [ -n "$caption" ] && printf "                 %s %s\n" "$(dim '└─')" "$(dim "$caption")"
    printf "   %s\n" "$(cyan "════════════════════════════════════════════════════════════════════════")"
    echo
}

# Conditional sub-section (e.g. host nginx + certbot setup) — no progress count.
subsection() {
    local title="$1"
    echo
    printf "   %s\n" "$(dim "──────────────────────────────────────────────────────────────────────")"
    printf "      %s\n" "$(bold "$title")"
    printf "   %s\n" "$(dim "──────────────────────────────────────────────────────────────────────")"
    echo
}

# Subtle "this section is done" footer between sections.
saved() {
    printf "      %s %s\n" "$(green '[+]')" "$(dim 'saved.')"
}

PROMPT_PREFIX="$(cyan '  > ')"

ask() {
    # ask "Prompt" "default" → echoes the answer
    local prompt="$1" default="${2:-}" reply
    if [ -n "$default" ]; then
        read -r -p "${PROMPT_PREFIX}${prompt} [${default}]: " reply
        echo "${reply:-$default}"
    else
        read -r -p "${PROMPT_PREFIX}${prompt}: " reply
        echo "$reply"
    fi
}

ask_required() {
    local prompt="$1" reply
    while :; do
        read -r -p "${PROMPT_PREFIX}${prompt}: " reply
        if [ -n "$reply" ]; then echo "$reply"; return; fi
        printf "    %s %s\n" "$(yellow '[!]')" "$(dim 'this one is required — please try again.')" >&2
    done
}

ask_yn() {
    # ask_yn "Prompt" "y"|"n" → 0 if yes, 1 if no
    local prompt="$1" default="${2:-n}" reply
    if [ "$default" = "y" ]; then
        read -r -p "${PROMPT_PREFIX}${prompt} (Y/n): " reply
        reply="${reply:-y}"
    else
        read -r -p "${PROMPT_PREFIX}${prompt} (y/N): " reply
        reply="${reply:-n}"
    fi
    [[ "$reply" =~ ^[Yy] ]]
}

ask_secret() {
    local prompt="$1" reply
    read -r -s -p "${PROMPT_PREFIX}${prompt}: " reply
    echo >&2
    echo "$reply"
}

# ── Header ─────────────────────────────────────────────────────────────────
clear || true
printf '\n'
printf '   %s\n' "$(yellow '##################################################################')"
printf '   %s\n' "$(yellow '#....@.......(......./.......)).......D............[?].....<.....#')"
printf '   %s\n' "$(yellow '#......................................$.........................#')"
printf '   %s\n' "$(yellow '#..............................................................T.#')"
printf '   %s\n' "$(yellow '#################+#################################################')"
printf '\n'
printf '   %s\n' "$(cyan '██████╗   ██████╗ ███████╗ ███████╗   ███████╗ ███████╗ ██████╗  ██╗   ██╗ ███████╗ ██████╗ ')"
printf '   %s\n' "$(cyan '██╔══██╗ ██╔════╝ ██╔════╝ ██╔════╝   ██╔════╝ ██╔════╝ ██╔══██╗ ██║   ██║ ██╔════╝ ██╔══██╗')"
printf '   %s\n' "$(cyan '██║  ██║ ██║      ███████╗ ███████╗   ███████╗ █████╗   ██████╔╝ ██║   ██║ █████╗   ██████╔╝')"
printf '   %s\n' "$(cyan '██║  ██║ ██║      ╚════██║ ╚════██║   ╚════██║ ██╔══╝   ██╔══██╗ ╚██╗ ██╔╝ ██╔══╝   ██╔══██╗')"
printf '   %s\n' "$(cyan '██████╔╝ ╚██████╗ ███████║ ███████║   ███████║ ███████╗ ██║  ██║  ╚████╔╝  ███████╗ ██║  ██║')"
printf '   %s\n' "$(cyan '╚═════╝   ╚═════╝ ╚══════╝ ╚══════╝   ╚══════╝ ╚══════╝ ╚═╝  ╚═╝   ╚═══╝   ╚══════╝ ╚═╝  ╚═╝')"
printf '\n'
printf '                              %s   %s\n' "$(bold "I N S T A L L E R")" "$(dim "v${VERSION}")"
printf '\n'
rule
printf '   %s  tarballqc  —  CRG · CBRG Server Admin\n'                    "$(bold 'maintainer ')"
printf '   %s  @tarballqc  ·  https://discord.gg/4Wattvg5Mh\n'             "$(bold 'discord    ')"
printf '   %s  tarballqc@roguelikes.gg\n'                                  "$(bold 'email      ')"
printf '   %s  https://github.com/tarballqc/dcss-server-install\n'         "$(bold 'repo       ')"
rule
printf '\n'
printf '   This wizard writes a .env file, optionally sets up host nginx + HTTPS,\n'
printf '   then prints the command to launch your server.\n'
printf '\n'
printf '   %s\n' "$(dim 'Press Ctrl+C at any time to abort.')"
printf '\n'
hr

# ── Pre-flight ─────────────────────────────────────────────────────────────
if [ -f .env ]; then
    if ask_yn "$(bold ".env already exists.") Overwrite?" "n"; then
        cp .env ".env.backup.$(date +%s)"
        echo "  $(dim "(backed up to .env.backup.<timestamp>)")"
    else
        echo "Aborted. Edit .env directly to make changes."
        exit 0
    fi
fi

command -v docker >/dev/null 2>&1 || { red "docker not found in PATH. Install Docker first (see docs/prereqs.md)."; echo; exit 1; }

# Compose v2 is a separate plugin on AL2023 / RHEL / many distros. If it's
# missing, offer to install the upstream binary into Docker's plugin path.
if ! docker compose version >/dev/null 2>&1; then
    echo
    echo "  $(yellow "▸ Docker Compose v2 plugin not found.")"
    echo "    On Amazon Linux 2023 and several RHEL-family distros it's a"
    echo "    separate plugin from the \`docker\` package, so this is normal"
    echo "    on a fresh box. The installer can fetch it for you."
    echo
    if ask_yn "  Install it now (downloads upstream binary, requires sudo)?" "y"; then
        ARCH="$(uname -m)"
        # Map common arch names to Docker's release filename suffixes.
        case "$ARCH" in
            x86_64|amd64) ARCH_SUFFIX="x86_64" ;;
            aarch64|arm64) ARCH_SUFFIX="aarch64" ;;
            armv7l|armhf) ARCH_SUFFIX="armv7" ;;
            *) ARCH_SUFFIX="$ARCH" ;;
        esac
        if command -v sudo >/dev/null 2>&1; then
            sudo mkdir -p /usr/local/lib/docker/cli-plugins
            sudo curl -fsSL --retry 3 \
                "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH_SUFFIX}" \
                -o /usr/local/lib/docker/cli-plugins/docker-compose
            sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
        else
            mkdir -p "$HOME/.docker/cli-plugins"
            curl -fsSL --retry 3 \
                "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH_SUFFIX}" \
                -o "$HOME/.docker/cli-plugins/docker-compose"
            chmod +x "$HOME/.docker/cli-plugins/docker-compose"
        fi
        if docker compose version >/dev/null 2>&1; then
            green "  ✓ Compose v2 installed: $(docker compose version --short 2>/dev/null || echo ok)"
        else
            red "  Install failed. See docs/prereqs.md for the manual steps."; echo
            exit 1
        fi
    else
        red "  Aborting. See docs/prereqs.md to install Compose v2 manually, then re-run."
        echo
        exit 1
    fi
fi

# `docker compose build` (Compose v2.30+) needs buildx 0.17.0+. AL2023's
# docker package ships ~0.11, which silently fails the very first build.
# Detect old/missing buildx and offer to install the upstream binary.
ensure_buildx() {
    local installed=""
    # Probe buildx via an `if` so a missing-plugin exit doesn't trip set -e,
    # and parse the version string with `|| true` to neutralize a no-match
    # grep failure under pipefail.
    if docker buildx version >/dev/null 2>&1; then
        local raw
        raw="$(docker buildx version 2>/dev/null | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
        installed="${raw#v}"
    fi
    # Need >= 0.17.0. sort -V -C returns 0 iff the input is in ascending order.
    if [ -n "$installed" ] && printf '0.17.0\n%s\n' "$installed" | sort -V -C 2>/dev/null; then
        return 0
    fi

    echo
    if [ -n "$installed" ]; then
        echo "  $(yellow "▸ Docker buildx ${installed} is too old.")"
        echo "    docker compose build needs 0.17.0+. AL2023's docker package"
        echo "    bundles 0.11.x, which fails the build silently."
    else
        echo "  $(yellow "▸ Docker buildx not found.")"
    fi
    echo
    if ask_yn "  Install latest buildx (downloads upstream binary, requires sudo)?" "y"; then
        local arch tag bx_arch dest
        arch="$(uname -m)"
        case "$arch" in
            x86_64|amd64)  bx_arch="amd64" ;;
            aarch64|arm64) bx_arch="arm64" ;;
            armv7l|armhf)  bx_arch="arm-v7" ;;
            *)             bx_arch="$arch" ;;
        esac
        tag="$(curl -fsSL https://api.github.com/repos/docker/buildx/releases/latest 2>/dev/null \
               | grep -o '"tag_name": *"[^"]*"' | head -1 | cut -d'"' -f4)"
        tag="${tag:-v0.18.0}"
        if command -v sudo >/dev/null 2>&1; then
            dest="/usr/local/lib/docker/cli-plugins/docker-buildx"
            sudo mkdir -p "$(dirname "$dest")"
            sudo curl -fsSL --retry 3 \
                "https://github.com/docker/buildx/releases/download/${tag}/buildx-${tag}.linux-${bx_arch}" \
                -o "$dest"
            sudo chmod +x "$dest"
        else
            dest="$HOME/.docker/cli-plugins/docker-buildx"
            mkdir -p "$(dirname "$dest")"
            curl -fsSL --retry 3 \
                "https://github.com/docker/buildx/releases/download/${tag}/buildx-${tag}.linux-${bx_arch}" \
                -o "$dest"
            chmod +x "$dest"
        fi
        if docker buildx version >/dev/null 2>&1; then
            ok "buildx installed: $(docker buildx version | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
        else
            fail "buildx install failed. See docs/prereqs.md for the manual steps."
            exit 1
        fi
    else
        red "  Aborting. Install buildx manually (docs/prereqs.md), then re-run."
        echo
        exit 1
    fi
}
ensure_buildx

# ── Server identity ────────────────────────────────────────────────────────
echo
section "01" "@   S E R V E R   I D E N T I T Y" "where on the internet your server lives."
SERVER_ABBR="$(ask_required "Server abbreviation (3-6 letters, e.g. ABC)")"
SERVER_HOST="$(ask_required "Public hostname (e.g. crawl.example.com)")"
SERVER_REGION_SHORT="$(ask "Region label (e.g. \"Eastern US\" or \"South America\")" "")"
SERVER_ADMIN="$(ask "Admin handle (shown as \"contact X on Discord\" — leave blank to omit)" "")"
SSH_PORT="$(ask "SSH play port (clients use this for in-terminal play)" "222")"

SERVER_URL="https://${SERVER_HOST}"

# ── SMTP ───────────────────────────────────────────────────────────────────
echo
saved

section "02" "!   S M T P   ·   F O R G O T   P A S S W O R D" "how Forgot Password emails get sent — pick a provider or skip."
echo

SMTP_HOST=""; SMTP_PORT="587"; SMTP_USER=""; SMTP_PASSWORD=""; SMTP_FROM=""; NOTIFY_EMAIL=""
SMTP_PROVIDER=""

printf "      %s) AWS SES        %s\n"      "$(cyan '1')" "$(dim 'email-smtp.<region>.amazonaws.com')"
printf "      %s) Mailgun         %s\n"      "$(cyan '2')" "$(dim 'smtp.mailgun.org · US or EU')"
printf "      %s) SendGrid        %s\n"      "$(cyan '3')" "$(dim 'smtp.sendgrid.net · "apikey" as user')"
printf "      %s) Postmark        %s\n"      "$(cyan '4')" "$(dim 'smtp.postmarkapp.com · token = user + pass')"
printf "      %s) Custom SMTP     %s\n"      "$(cyan '5')" "$(dim 'bring your own host : port + creds')"
printf "      %s) Skip for now    %s\n"      "$(cyan '6')" "$(dim 'disable Forgot Password until later')"
echo
read -r -p "${PROMPT_PREFIX}Choice [6]: " smtp_choice
smtp_choice="${smtp_choice:-6}"

case "$smtp_choice" in
    1)
        SMTP_PROVIDER="AWS SES"
        SES_REGION="$(ask "AWS region (e.g. us-east-1, eu-west-1, ap-southeast-2)" "us-east-1")"
        SMTP_HOST="email-smtp.${SES_REGION}.amazonaws.com"
        SMTP_PORT=587
        echo
        echo "$(dim "  Get SMTP credentials in the SES console:")"
        echo "$(dim "    SMTP Settings → Create SMTP Credentials  (NOT your IAM access keys.)")"
        SMTP_USER="$(ask_required "SES SMTP user (starts with AKIA…)")"
        SMTP_PASSWORD="$(ask_secret "SES SMTP password")"
        echo "$(dim "  Your From address must be verified in SES, or you stay sandboxed.")"
        SMTP_FROM="$(ask "From address" "DCSS WebTiles <admin@${SERVER_HOST}>")"
        ;;
    2)
        SMTP_PROVIDER="Mailgun"
        echo "    1) US region (smtp.mailgun.org)"
        echo "    2) EU region (smtp.eu.mailgun.org)"
        read -r -p "${PROMPT_PREFIX}Region [1]: " mg_region
        if [ "$mg_region" = "2" ]; then
            SMTP_HOST="smtp.eu.mailgun.org"
        else
            SMTP_HOST="smtp.mailgun.org"
        fi
        SMTP_PORT=587
        echo
        echo "$(dim "  Get SMTP credentials in the Mailgun dashboard:")"
        echo "$(dim "    Sending → Domains → <your domain> → SMTP credentials")"
        SMTP_USER="$(ask_required "Mailgun SMTP user (e.g. postmaster@mg.yourdomain.com)")"
        SMTP_PASSWORD="$(ask_secret "Mailgun SMTP password")"
        SMTP_FROM="$(ask "From address" "DCSS WebTiles <admin@${SERVER_HOST}>")"
        ;;
    3)
        SMTP_PROVIDER="SendGrid"
        SMTP_HOST="smtp.sendgrid.net"
        SMTP_PORT=587
        echo
        echo "$(dim "  SendGrid SMTP user is literally the string 'apikey'.")"
        echo "$(dim "  Password is your SendGrid API key (Settings → API Keys).")"
        SMTP_USER="apikey"
        SMTP_PASSWORD="$(ask_secret "SendGrid API key (used as SMTP password)")"
        SMTP_FROM="$(ask "From address (must be a verified sender in SendGrid)" "DCSS WebTiles <admin@${SERVER_HOST}>")"
        ;;
    4)
        SMTP_PROVIDER="Postmark"
        SMTP_HOST="smtp.postmarkapp.com"
        SMTP_PORT=587
        echo
        echo "$(dim "  Postmark SMTP uses your Server API Token for both user and password.")"
        echo "$(dim "  Find it in Postmark → Servers → <your server> → API Tokens.")"
        POSTMARK_TOKEN="$(ask_secret "Postmark Server API Token")"
        SMTP_USER="$POSTMARK_TOKEN"
        SMTP_PASSWORD="$POSTMARK_TOKEN"
        SMTP_FROM="$(ask "From address (must be a confirmed Sender Signature in Postmark)" "DCSS WebTiles <admin@${SERVER_HOST}>")"
        ;;
    5)
        SMTP_PROVIDER="Custom"
        SMTP_HOST="$(ask_required "SMTP host")"
        SMTP_PORT="$(ask "SMTP port" "587")"
        SMTP_USER="$(ask_required "SMTP user")"
        SMTP_PASSWORD="$(ask_secret "SMTP password")"
        SMTP_FROM="$(ask "From address" "DCSS WebTiles <admin@${SERVER_HOST}>")"
        ;;
    *)
        SMTP_PROVIDER="Skipped"
        echo "  $(dim "Skipping SMTP. Add credentials to .env later and re-run ./run.sh banner to enable.")"
        ;;
esac

if [ -n "$SMTP_HOST" ]; then
    NOTIFY_EMAIL="$(ask "Notify email (optional, for server alerts from the release-checker)" "")"

    # ── Optional test email ────────────────────────────────────────────────
    echo
    if ask_yn "Send a test email now to verify these credentials?" "y"; then
        TEST_TO="$(ask_required "Test recipient address")"
        if command -v python3 >/dev/null 2>&1; then
            echo "  $(dim "Connecting to ${SMTP_HOST}:${SMTP_PORT}…")"
            if SMTP_HOST="$SMTP_HOST" SMTP_PORT="$SMTP_PORT" \
               SMTP_USER="$SMTP_USER" SMTP_PASSWORD="$SMTP_PASSWORD" \
               SMTP_FROM="$SMTP_FROM" SMTP_TO="$TEST_TO" \
               SERVER_ABBR="$SERVER_ABBR" \
               python3 - <<'PY'
import os, smtplib, sys
from email.mime.text import MIMEText
m = MIMEText(f"This is a test email from your dcss-server-install setup wizard.\nIf you got this, password reset will work on {os.environ['SERVER_ABBR']}.")
m["Subject"] = f"SMTP test — {os.environ['SERVER_ABBR']}"
m["From"]    = os.environ["SMTP_FROM"]
m["To"]      = os.environ["SMTP_TO"]
try:
    s = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"]), timeout=15)
    s.ehlo()
    s.starttls()
    s.ehlo()
    s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
    s.send_message(m)
    s.quit()
    print("  \033[32m✓\033[0m Test email sent. Check the inbox at", os.environ["SMTP_TO"])
    sys.exit(0)
except smtplib.SMTPAuthenticationError as e:
    print("  \033[31m✗\033[0m Authentication failed:", e.smtp_error.decode("utf-8", "replace") if e.smtp_error else e)
    sys.exit(2)
except smtplib.SMTPException as e:
    print("  \033[31m✗\033[0m SMTP error:", e)
    sys.exit(2)
except Exception as e:
    print("  \033[31m✗\033[0m Connection error:", e)
    sys.exit(2)
PY
            then
                :
            else
                echo
                if ask_yn "Test failed. Re-enter SMTP credentials?" "n"; then
                    SMTP_USER="$(ask_required "SMTP user")"
                    SMTP_PASSWORD="$(ask_secret "SMTP password")"
                    echo "  $(dim "(re-test by editing .env and running install.sh again, or send manually after deploy)")"
                fi
            fi
        else
            echo "  $(dim "python3 not found on host — skipping test. Test from inside the container after deploy.")"
        fi
    fi
fi

# ── Discord bot ────────────────────────────────────────────────────────────
echo
saved

section "03" "D   D I S C O R D   B O T   ·   O P T I O N A L" "post wins / deaths / milestones to a channel — bring your own bot token."
echo

DISCORD_BOT_TOKEN=""; DISCORD_GUILD_ID=""; DISCORD_CHANNEL_ID=""; DISCORD_INVITE=""
ENABLE_DISCORD="0"
if ask_yn "Enable Discord bot?" "n"; then
    ENABLE_DISCORD="1"
    DISCORD_BOT_TOKEN="$(ask_secret "Bot token")"
    DISCORD_GUILD_ID="$(ask_required "Guild (server) ID")"
    DISCORD_CHANNEL_ID="$(ask_required "Channel ID")"
    DISCORD_INVITE="$(ask "Invite code (optional, shown in emails)" "")"
fi

# ── Imported-account hint ──────────────────────────────────────────────────
echo
saved

section "04" "?   I M P O R T E D   A C C O U N T S   ·   O P T I O N A L" "tell players who imported from another server their old password still works."
echo

IMPORT_SOURCE_NAME=""; IMPORT_SOURCE_URL=""; IMPORT_DATE=""
if ask_yn "Did you import accounts from another DCSS server?" "n"; then
    IMPORT_SOURCE_NAME="$(ask_required "Source server name (e.g. CAO, CDI)")"
    IMPORT_SOURCE_URL="$(ask "Source server URL (e.g. crawl.akrasiac.org)" "")"
    IMPORT_DATE="$(ask "Import date (e.g. \"April 25, 2026\")" "")"
fi

# ── Older versions ─────────────────────────────────────────────────────────
echo
saved

section "05" "<   O L D E R   D C S S   V E R S I O N S   ·   A D V A N C E D" "default 0.34 + trunk only; older versions add ~45 min to first build."
echo

DOCKERFILE_GAME="Dockerfile.game"
GAMES_YAML="config/games.d/crawl.yaml"
if ask_yn "Build older versions (0.30-0.33) too?" "n"; then
    DOCKERFILE_GAME="Dockerfile.game.full"
    cp config/games.d/crawl.yaml.full config/games.d/crawl.yaml
    echo "  $(green "Older versions enabled.") Run scripts/build-frozen.sh before first deploy."
fi

# ── HTTPS / host nginx ────────────────────────────────────────────────────
echo
saved

section "06" "=   H T T P S   ·   N G I N X   +   C E R T B O T" "host nginx + Let's Encrypt cert; skip if TLS lives elsewhere (Cloudflare, ELB)."
echo

SETUP_TLS="0"
if ask_yn "Set up host nginx + certbot now?" "n"; then
    SETUP_TLS="1"
fi

# ── Summary ────────────────────────────────────────────────────────────────
echo
saved

section "07" "*   S U M M A R Y" "review what we'll write to .env."
printf "  Server:              %s\n" "$(green "$SERVER_ABBR ($SERVER_HOST)")"
printf "  Region:              %s\n" "${SERVER_REGION_SHORT:-$(dim "(none)")}"
printf "  SSH play port:       %s\n" "$SSH_PORT"
printf "  SMTP:                %s\n" "${SMTP_HOST:+$SMTP_PROVIDER ($SMTP_HOST:$SMTP_PORT)}${SMTP_HOST:-$(dim "disabled")}"
printf "  Discord bot:         %s\n" "$([ "$ENABLE_DISCORD" = 1 ] && echo "$(green "enabled")" || dim "disabled")"
printf "  Imported users:      %s\n" "${IMPORT_SOURCE_NAME:-$(dim "none")}"
printf "  Older versions:      %s\n" "$([ "$DOCKERFILE_GAME" = Dockerfile.game.full ] && echo "$(green "yes (0.30-0.33)")" || dim "no (0.34+trunk)")"
printf "  HTTPS setup now:     %s\n" "$([ "$SETUP_TLS" = 1 ] && echo "$(green "yes")" || dim "no")"
echo

if ! ask_yn "Write .env and continue?" "y"; then
    echo "Aborted."; exit 1
fi

# ── Write .env ─────────────────────────────────────────────────────────────
{
    echo "# Generated by install.sh on $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "# Edit freely; re-run install.sh to regenerate."
    echo ""
    echo "# ── Server identity ────────────────────────────────────────────"
    echo "SERVER_ABBR=$SERVER_ABBR"
    echo "SERVER_URL=$SERVER_URL"
    if [ -n "$SERVER_REGION_SHORT" ]; then
        echo "SERVER_REGION_SHORT=\"$SERVER_REGION_SHORT\""
        echo "SERVER_REGION=\"$SERVER_REGION_SHORT\""
    fi
    [ -n "$SERVER_ADMIN" ] && echo "SERVER_ADMIN=\"$SERVER_ADMIN\""
    echo "SSH_PORT=$SSH_PORT"
    echo ""
    if [ -n "$SMTP_HOST" ]; then
        echo "# ── SMTP ───────────────────────────────────────────────────────"
        echo "SMTP_HOST=$SMTP_HOST"
        echo "SMTP_PORT=$SMTP_PORT"
        echo "SMTP_USER=$SMTP_USER"
        echo "SMTP_PASSWORD=$SMTP_PASSWORD"
        echo "SMTP_FROM=\"$SMTP_FROM\""
        [ -n "$NOTIFY_EMAIL" ] && echo "NOTIFY_EMAIL=$NOTIFY_EMAIL"
        echo ""
    fi
    if [ "$ENABLE_DISCORD" = "1" ]; then
        echo "# ── Discord bot ────────────────────────────────────────────────"
        echo "DISCORD_BOT_TOKEN=$DISCORD_BOT_TOKEN"
        echo "DISCORD_GUILD_ID=$DISCORD_GUILD_ID"
        echo "DISCORD_CHANNEL_ID=$DISCORD_CHANNEL_ID"
        [ -n "$DISCORD_INVITE" ] && echo "DISCORD_INVITE=$DISCORD_INVITE"
        echo ""
    fi
    if [ -n "$IMPORT_SOURCE_NAME" ]; then
        echo "# ── Imported users ─────────────────────────────────────────────"
        echo "IMPORT_SOURCE_NAME=$IMPORT_SOURCE_NAME"
        [ -n "$IMPORT_SOURCE_URL" ] && echo "IMPORT_SOURCE_URL=$IMPORT_SOURCE_URL"
        [ -n "$IMPORT_DATE" ] && echo "IMPORT_DATE=\"$IMPORT_DATE\""
        echo ""
    fi
    if [ "$DOCKERFILE_GAME" != "Dockerfile.game" ]; then
        echo "# ── Build flags ────────────────────────────────────────────────"
        echo "DOCKERFILE_GAME=$DOCKERFILE_GAME"
    fi
} > .env

green "  ✓ .env written ($(wc -l <.env | tr -d ' ') lines)"; echo

# ── Optional: host nginx + certbot ─────────────────────────────────────────
if [ "$SETUP_TLS" = "1" ]; then
    echo
    subsection "Setting up host nginx + certbot"

    if ! command -v sudo >/dev/null 2>&1; then
        red "  sudo not available; can't install nginx/certbot. Skipping TLS setup."
        echo "  Set up nginx + TLS manually using nginx/dcss-host.conf as a template."
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo apt-get install -y nginx certbot python3-certbot-nginx
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y nginx certbot python3-certbot-nginx
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y nginx certbot python3-certbot-nginx
    else
        red "  No supported package manager (apt/dnf/yum) found."
        echo "  Install nginx + certbot manually, then point a vhost at 127.0.0.1:8880."
    fi

    if command -v certbot >/dev/null 2>&1; then
        # Render the nginx vhost template
        sed -e "s|__SERVER_HOST__|$SERVER_HOST|g" \
            nginx/dcss-host.conf > /tmp/dcss-host.conf
        sudo cp /tmp/dcss-host.conf "/etc/nginx/conf.d/${SERVER_ABBR,,}.conf"
        sudo nginx -t && sudo systemctl reload nginx || true

        echo
        echo "  Now provisioning a Let's Encrypt cert for $SERVER_HOST."
        echo "  Make sure $SERVER_HOST already resolves to this server's IP."
        echo
        if ask_yn "Run certbot now?" "y"; then
            sudo certbot --nginx -d "$SERVER_HOST"
        fi
    fi
fi

# ── Done ───────────────────────────────────────────────────────────────────
echo
hr
echo
printf '   %s\n' "$(green '██████╗  ███████╗  █████╗  ██████╗  ██╗   ██╗   ██╗')"
printf '   %s\n' "$(green '██╔══██╗ ██╔════╝ ██╔══██╗ ██╔══██╗ ╚██╗ ██╔╝   ██║')"
printf '   %s\n' "$(green '██████╔╝ █████╗   ███████║ ██║  ██║  ╚████╔╝    ██║')"
printf '   %s\n' "$(green '██╔══██╗ ██╔══╝   ██╔══██║ ██║  ██║   ╚██╔╝     ╚═╝')"
printf '   %s\n' "$(green '██║  ██║ ███████╗ ██║  ██║ ██████╔╝    ██║      ██╗')"
printf '   %s\n' "$(green '╚═╝  ╚═╝ ╚══════╝ ╚═╝  ╚═╝ ╚═════╝     ╚═╝      ╚═╝')"
echo
ok ".env written to $(bold "$PWD/.env")"
ok "configured for $(bold "$SERVER_ABBR") at $(bold "$SERVER_URL")"
echo
if [ "$DOCKERFILE_GAME" = "Dockerfile.game.full" ]; then
    note "Older versions enabled — run this once first (~45 min):"
    printf '       %s\n\n'   "$(green 'bash scripts/build-frozen.sh')"
fi

# Render the run command with ~ shorthand if we're under $HOME, abs path otherwise.
RUN_PATH="$PWD"
if [[ "$RUN_PATH" == "$HOME"/* ]]; then
    RUN_PATH="~${RUN_PATH#$HOME}"
fi
RUN_CMD="cd $RUN_PATH && ./run.sh game"

# Offer to launch right now — most polished hand-off, but not forced.
if ask_yn "Build and launch the server right now? (full build, ~20 min)" "y"; then
    echo
    info "starting in 3 seconds — Ctrl+C to abort and run it later."
    sleep 3
    echo
    exec bash "$PWD/run.sh" game
fi

echo
echo "   $(bold "When you're ready:")"
printf '       %s\n'             "$(green "$RUN_CMD")"
printf '       %s\n'             "$(dim '(full build + boot, ~20 min)')"
echo
echo "   $(bold 'After it boots:')"
printf '       browser   %s\n'    "$(cyan "$SERVER_URL")"
printf '       ssh play  %s\n'    "$(cyan "ssh -p $SSH_PORT crawl@$SERVER_HOST")"
echo
rule
printf '   %s   %s\n'   "$(dim 'docs   ')" "docs/"
printf '   %s   %s\n'   "$(dim 'issues ')" "https://github.com/tarballqc/dcss-server-install/issues"
printf '   %s   %s\n'   "$(dim 'discord')" "https://discord.gg/4Wattvg5Mh  ·  @tarballqc"
printf '   %s   %s\n'   "$(dim 'email  ')" "tarballqc@roguelikes.gg"
rule
printf '   %s\n' "$(dim "       dcss-server-install · v${VERSION} · MIT · @tarballqc")"
echo
