#!/bin/bash
# DCSS release checker (runs twice daily).
# Checks for new stable point releases and trunk updates.
# Verifies running binaries match expected state (catches stale Docker cache).
# Rebuilds and deploys automatically, sends email on success or failure.
# No email if no updates are available.
#
# Frozen versions (0.30-0.33) are not checked — they are built once and never rebuilt.
#
# Cron (twice daily at 6 AM and 9 PM UTC — timed to catch trunk commit peaks):
#   0 6,21 * * * /path/to/dcss-server-install/scripts/check-releases.sh >> /var/log/dcss-release-check.log 2>&1
#
# Environment (from .env):
#   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
#   NOTIFY_EMAIL — recipient for release notifications

set -euo pipefail
cd "$(dirname "$0")/.."

# Pull latest repo changes early so this script is always current
git pull --quiet 2>/dev/null || true

# Load SMTP credentials from .env (line-by-line to handle values with spaces/angles)
if [ -f .env ]; then
    while IFS= read -r line; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        [[ "$line" =~ ^(SMTP_|NOTIFY_EMAIL=|SERVER_ABBR=|SERVER_URL=) ]] && export "$line"
    done < .env
fi

NOTIFY_EMAIL="${NOTIFY_EMAIL:-}"
SMTP_HOST="${SMTP_HOST:-email-smtp.us-east-1.amazonaws.com}"
SMTP_PORT="${SMTP_PORT:-587}"
SMTP_USER="${SMTP_USER:-}"
SMTP_PASSWORD="${SMTP_PASSWORD:-}"
SERVER_ABBR="${SERVER_ABBR:-MYSRV}"
SERVER_URL="${SERVER_URL:-https://my-server.example.com}"
SMTP_FROM="${SMTP_FROM:-${SERVER_ABBR} <admin@my-server.example.com>}"

LOG_PREFIX="[release-check $(date -u '+%Y-%m-%d %H:%M UTC')]"

# ── Email helper ──────────────────────────────────────────────────────────────
send_email() {
    local subject="$1"
    local body="$2"

    if [ -z "$SMTP_USER" ] || [ -z "$SMTP_PASSWORD" ]; then
        echo "$LOG_PREFIX WARNING: SMTP credentials not configured, skipping email"
        return 1
    fi

    python3 << PYEOF
import smtplib
from email.mime.text import MIMEText

msg = MIMEText("""$body""")
msg['Subject'] = "$subject"
msg['From'] = "$SMTP_FROM"
msg['To'] = "$NOTIFY_EMAIL"

try:
    server = smtplib.SMTP("$SMTP_HOST", $SMTP_PORT)
    server.starttls()
    server.login("$SMTP_USER", "$SMTP_PASSWORD")
    server.sendmail("$SMTP_FROM", "$NOTIFY_EMAIL", msg.as_string())
    server.quit()
    print("Email sent")
except Exception as e:
    print(f"Email failed: {e}")
PYEOF
}

echo "$LOG_PREFIX Starting release check..."

# ── Check latest stable tag from GitHub ──────────────────────────────────────
# Tags are bare versions like "0.34.1" (not "stone_soup-0.34.1")
# Filter to 0.{30+}.x.y only — exclude alpha/beta/rc tags (e.g. 0.35-a0, 0.34-b1)
LATEST_STABLE_TAG=$(git ls-remote --tags https://github.com/crawl/crawl.git 'refs/tags/0.3*' 2>/dev/null \
  | grep -v '\^{}' | sed 's|.*/||' | grep -E '^0\.[0-9]+\.[0-9]+$' | sort -V | tail -1 || echo "")

echo "$LOG_PREFIX Latest stable tag: ${LATEST_STABLE_TAG:-unknown}"

# ── Check if trunk has new commits ───────────────────────────────────────────
TRUNK_LATEST=$(curl -sf "https://api.github.com/repos/crawl/crawl/commits/master" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['sha'][:8])" 2>/dev/null || echo "")

TRUNK_STATE_FILE=".trunk-last-commit"
TRUNK_LAST=$(cat "$TRUNK_STATE_FILE" 2>/dev/null || echo "")

echo "$LOG_PREFIX Trunk latest: ${TRUNK_LATEST:-unknown}, last deployed: ${TRUNK_LAST:-none}"

NEEDS_REBUILD=false
CHANGES=""

# ── Check if stable needs update ─────────────────────────────────────────────
STABLE_STATE_FILE=".stable-last-tag"
STABLE_LAST=$(cat "$STABLE_STATE_FILE" 2>/dev/null || echo "")

if [ -n "$LATEST_STABLE_TAG" ] && [ "$LATEST_STABLE_TAG" != "$STABLE_LAST" ]; then
    # Detect major version bump (e.g. 0.34.x -> 0.35.0) — requires manual upgrade
    CURRENT_MAJOR=$(echo "${STABLE_LAST:-0.0.0}" | grep -oP '^\d+\.\d+')
    NEW_MAJOR=$(echo "$LATEST_STABLE_TAG" | grep -oP '^\d+\.\d+')

    if [ -n "$CURRENT_MAJOR" ] && [ -n "$NEW_MAJOR" ] && [ "$CURRENT_MAJOR" != "$NEW_MAJOR" ]; then
        echo "$LOG_PREFIX MAJOR VERSION BUMP detected: $CURRENT_MAJOR -> $NEW_MAJOR"
        echo "$LOG_PREFIX Running automated upgrade: $CURRENT_MAJOR -> $NEW_MAJOR"

        send_email "[${SERVER_ABBR}] DCSS Major Version Upgrade Starting: $CURRENT_MAJOR → $NEW_MAJOR" \
            "A new major DCSS version has been detected and the automated upgrade is starting.

Current stable: $STABLE_LAST (branch stone_soup-$CURRENT_MAJOR)
New version:    $LATEST_STABLE_TAG (branch stone_soup-$NEW_MAJOR)

The upgrade script will:
  1. Build frozen image for $CURRENT_MAJOR (~15 min)
  2. Update all config files
  3. Migrate save/RC data
  4. Rebuild and deploy $NEW_MAJOR (~20 min, ~5 sec downtime)

You'll receive another email when it completes (or fails).

Timestamp: $(date -u '+%Y-%m-%d %H:%M UTC')"

        UPGRADE_LOG=$(mktemp)
        if bash scripts/upgrade-stable.sh "$NEW_MAJOR" 2>&1 | tee "$UPGRADE_LOG"; then
            echo "$LOG_PREFIX Major version upgrade SUCCEEDED: $CURRENT_MAJOR -> $NEW_MAJOR"
            send_email "[${SERVER_ABBR}] DCSS Major Version Upgrade SUCCEEDED: $NEW_MAJOR" \
                "The automated upgrade completed successfully!

$CURRENT_MAJOR has been frozen (like 0.30-0.33).
$NEW_MAJOR is now the active stable version.

Verify at: ${SERVER_URL}

Timestamp: $(date -u '+%Y-%m-%d %H:%M UTC')"
        else
            echo "$LOG_PREFIX Major version upgrade FAILED"
            FAIL_TAIL=$(tail -50 "$UPGRADE_LOG")
            send_email "[${SERVER_ABBR}] DCSS Major Version Upgrade FAILED: $CURRENT_MAJOR → $NEW_MAJOR" \
                "The automated upgrade from $CURRENT_MAJOR to $NEW_MAJOR FAILED.

Last 50 lines of output:

$FAIL_TAIL

You may need to intervene manually:
    ssh into ${SERVER_ABBR} server
    cd "$(dirname "$0")/.."
    # Check git status, docker ps, etc.

Timestamp: $(date -u '+%Y-%m-%d %H:%M UTC')"
        fi
        rm -f "$UPGRADE_LOG"
        exit 0
    fi

    echo "$LOG_PREFIX Stable update available: $STABLE_LAST -> $LATEST_STABLE_TAG"
    NEEDS_REBUILD=true
    CHANGES="${CHANGES}Stable: ${STABLE_LAST:-none} -> $LATEST_STABLE_TAG\n"
fi

# ── Check if trunk needs update ──────────────────────────────────────────────
if [ -n "$TRUNK_LATEST" ] && [ "$TRUNK_LATEST" != "$TRUNK_LAST" ]; then
    echo "$LOG_PREFIX Trunk update available: $TRUNK_LAST -> $TRUNK_LATEST"
    NEEDS_REBUILD=true
    CHANGES="${CHANGES}Trunk: ${TRUNK_LAST:-none} -> $TRUNK_LATEST\n"
fi

# ── Check if stable branch tip has new commits (post-release fixes) ──────────
STABLE_BRANCH_SHA=$(git ls-remote https://github.com/crawl/crawl.git refs/heads/stone_soup-0.34 2>/dev/null | cut -f1 | head -c8)
STABLE_BRANCH_STATE_FILE=".stable-branch-last-commit"
STABLE_BRANCH_LAST=$(cat "$STABLE_BRANCH_STATE_FILE" 2>/dev/null || echo "")

if [ -n "$STABLE_BRANCH_SHA" ] && [ "$STABLE_BRANCH_SHA" != "$STABLE_BRANCH_LAST" ]; then
    echo "$LOG_PREFIX Stable branch tip update: $STABLE_BRANCH_LAST -> $STABLE_BRANCH_SHA"
    NEEDS_REBUILD=true
    CHANGES="${CHANGES}Stable branch: ${STABLE_BRANCH_LAST:-none} -> $STABLE_BRANCH_SHA\n"
fi

# ── Verify running binaries match state (catches stale Docker cache) ─────────
# Safety net: if a manual rebuild used stale cache, the state file says one thing
# but the running binary is something else. Force a rebuild to correct it.
if [ "$NEEDS_REBUILD" = false ]; then
    # Check trunk binary
    if [ -n "$TRUNK_LAST" ]; then
        RUNNING_TRUNK=$(docker exec dcss-game-1 /app/source-trunk/crawl -version 2>/dev/null | head -1 || echo "")
        if [ -n "$RUNNING_TRUNK" ] && ! echo "$RUNNING_TRUNK" | grep -q "$TRUNK_LAST"; then
            echo "$LOG_PREFIX MISMATCH: Running trunk ($RUNNING_TRUNK) doesn't match state ($TRUNK_LAST). Forcing rebuild."
            NEEDS_REBUILD=true
            CHANGES="${CHANGES}Trunk binary mismatch: $RUNNING_TRUNK (expected $TRUNK_LAST)\n"
        fi
    fi

    # Check stable binary
    if [ -n "$STABLE_BRANCH_LAST" ]; then
        RUNNING_STABLE=$(docker exec dcss-game-1 /app/source/crawl -version 2>/dev/null | head -1 || echo "")
        if [ -n "$RUNNING_STABLE" ] && ! echo "$RUNNING_STABLE" | grep -q "$STABLE_BRANCH_LAST"; then
            echo "$LOG_PREFIX MISMATCH: Running stable ($RUNNING_STABLE) doesn't match state ($STABLE_BRANCH_LAST). Forcing rebuild."
            NEEDS_REBUILD=true
            CHANGES="${CHANGES}Stable binary mismatch: $RUNNING_STABLE (expected $STABLE_BRANCH_LAST)\n"
        fi
    fi
fi

if [ "$NEEDS_REBUILD" = false ]; then
    echo "$LOG_PREFIX No updates found. All versions current."
    exit 0
fi

# ── Rebuild game container ────────────────────────────────────────────────────
echo "$LOG_PREFIX Rebuilding game container..."

# Cache bust via env vars (read by docker-compose.yml build args)
export TRUNK_CACHE_BUST="$(date +%s)"
export STABLE_CACHE_BUST="$(date +%s)"

# Capture build output for failure email
BUILD_LOG=$(mktemp)
trap 'rm -f "$BUILD_LOG"' EXIT

if ! docker compose build game 2>&1 | tee "$BUILD_LOG"; then
    echo "$LOG_PREFIX BUILD FAILED"
    FAIL_TAIL=$(tail -30 "$BUILD_LOG")
    send_email "[${SERVER_ABBR}] DCSS Update FAILED — Build Error" \
        "The DCSS auto-update failed during docker build on ${SERVER_URL#https://}.

Changes attempted:
$(echo -e "$CHANGES")
Last 30 lines of build output:

$FAIL_TAIL

Timestamp: $(date -u '+%Y-%m-%d %H:%M UTC')"
    exit 1
fi

if ! docker compose up -d game 2>&1 | tee -a "$BUILD_LOG"; then
    echo "$LOG_PREFIX DEPLOY FAILED"
    FAIL_TAIL=$(tail -30 "$BUILD_LOG")
    send_email "[${SERVER_ABBR}] DCSS Update FAILED — Deploy Error" \
        "The DCSS auto-update failed during deploy on ${SERVER_URL#https://}.
Build succeeded but 'docker compose up -d game' failed.

Changes attempted:
$(echo -e "$CHANGES")
Last 30 lines of output:

$FAIL_TAIL

Timestamp: $(date -u '+%Y-%m-%d %H:%M UTC')"
    exit 1
fi

# Wait for container to become healthy
echo "$LOG_PREFIX Waiting for health check..."
HEALTHY=false
for i in $(seq 1 12); do
    sleep 10
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' dcss-game-1 2>/dev/null || echo "unknown")
    if [ "$STATUS" = "healthy" ]; then
        HEALTHY=true
        break
    fi
    echo "$LOG_PREFIX Health check attempt $i/12: $STATUS"
done

if [ "$HEALTHY" = false ]; then
    echo "$LOG_PREFIX HEALTH CHECK FAILED"
    CONTAINER_LOGS=$(docker compose logs --tail=30 game 2>/dev/null || echo "(could not fetch logs)")
    send_email "[${SERVER_ABBR}] DCSS Update FAILED — Health Check" \
        "The DCSS auto-update deployed but the container failed health checks on ${SERVER_URL#https://}.

Changes deployed:
$(echo -e "$CHANGES")
Container logs (last 30 lines):

$CONTAINER_LOGS

Timestamp: $(date -u '+%Y-%m-%d %H:%M UTC')"
    exit 1
fi

echo "$LOG_PREFIX Deployment complete and healthy."

# ── Update state files ───────────────────────────────────────────────────────
[ -n "$LATEST_STABLE_TAG" ] && echo "$LATEST_STABLE_TAG" > "$STABLE_STATE_FILE"
[ -n "$TRUNK_LATEST" ] && echo "$TRUNK_LATEST" > "$TRUNK_STATE_FILE"
[ -n "$STABLE_BRANCH_SHA" ] && echo "$STABLE_BRANCH_SHA" > "$STABLE_BRANCH_STATE_FILE"

# ── Send success email ───────────────────────────────────────────────────────
send_email "[${SERVER_ABBR}] DCSS Update Deployed Successfully" \
    "DCSS has been updated on ${SERVER_URL#https://}.

Changes:
$(echo -e "$CHANGES")
Timestamp: $(date -u '+%Y-%m-%d %H:%M UTC')"

echo "$LOG_PREFIX Release check complete."
