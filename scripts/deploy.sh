#!/bin/bash
# scripts/deploy.sh — Unified deploy
# Always busts Docker cache for game builds to prevent stale trunk/stable binaries.
#
# Usage:
#   deploy.sh              # Full game rebuild (default)
#   deploy.sh game         # Full game rebuild
#   deploy.sh scoring      # Rebuild scoring container only
#   deploy.sh web          # Restart nginx (static file changes)
#   deploy.sh config       # Restart game (config-only changes, games.d/webtiles.py)
#   deploy.sh banner       # Update banner (docker cp + restart, no rebuild)
#   deploy.sh all          # Rebuild all services
#
# From local machine:
#   ssh user@your-server \
#     "cd ~/dcss-server-install && git pull && bash scripts/deploy.sh [mode]"

set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-game}"

# ── Render host-mounted nginx templates ──────────────────────────────────
# Substitute __SERVER_ABBR__ / __SERVER_URL__ / __SERVER_HOST__ from .env
# into nginx/html/*.template → live nginx/html/* files (gitignored).
# Use grep instead of `. ./.env` so unquoted values with spaces/emoji
# (e.g. SERVER_REGION="Oregon, USA") don't break the shell parser.
read_env() {
    local key="$1"
    [ -f .env ] || return 0
    # `|| true` so a missing key doesn't trip pipefail+set -e under the caller.
    { grep -E "^${key}=" .env 2>/dev/null || true; } | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//" | tr -d '\r'
}
SA="$(read_env SERVER_ABBR)"; SA="${SA:-MYSRV}"
SU="$(read_env SERVER_URL)";  SU="${SU:-https://my-server.example.com}"
SH="${SU#https://}"
SH="${SH#http://}"
for tmpl in nginx/html/*.template; do
    [ -f "$tmpl" ] || continue
    out="${tmpl%.template}"
    sed -e "s|__SERVER_URL__|${SU}|g" \
        -e "s|__SERVER_HOST__|${SH}|g" \
        -e "s/__SERVER_ABBR__/${SA}/g" \
        "$tmpl" > "$out"
done
echo "[render] nginx/html templates rendered for ${SA} (${SH})"

echo "=== ${SA} Deploy ($MODE): $(date -u '+%Y-%m-%d %H:%M:%S UTC') ==="

case "$MODE" in
  game|full)
    # Compose v2.30+ needs buildx 0.17.0+; AL2023 ships ~0.11. Fail fast with
    # a copy-pasteable upgrade hint instead of letting `compose build` hang.
    # Parse defensively so a missing-plugin exit / no-match grep doesn't trip
    # set -e under pipefail.
    BX_VER=""
    if docker buildx version >/dev/null 2>&1; then
        BX_RAW="$(docker buildx version 2>/dev/null | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
        BX_VER="${BX_RAW#v}"
    fi
    if [ -z "$BX_VER" ] || ! printf '0.17.0\n%s\n' "$BX_VER" | sort -V -C 2>/dev/null; then
        echo
        echo "  buildx ${BX_VER:-not found} is too old — docker compose build needs 0.17.0+."
        echo "  Install the latest with:"
        echo
        echo "    BX_TAG=\$(curl -fsSL https://api.github.com/repos/docker/buildx/releases/latest | grep tag_name | cut -d'\"' -f4)"
        echo "    ARCH=\$(uname -m); [ \"\$ARCH\" = x86_64 ] && ARCH=amd64; [ \"\$ARCH\" = aarch64 ] && ARCH=arm64"
        echo "    sudo curl -fsSL \"https://github.com/docker/buildx/releases/download/\${BX_TAG}/buildx-\${BX_TAG}.linux-\${ARCH}\" \\"
        echo "        -o /usr/local/lib/docker/cli-plugins/docker-buildx"
        echo "    sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx"
        echo
        echo "  Or re-run ./install.sh — it'll offer to do this for you."
        exit 1
    fi
    echo "Full game rebuild (cache bust enabled)..."
    export TRUNK_CACHE_BUST=$(date +%s)
    export STABLE_CACHE_BUST=$(date +%s)
    docker compose build game
    # Bring up the whole stack — `up -d game` alone leaves web (nginx) and
    # scoring down on first install, so the public site would 404. With no
    # service arg, compose starts game first, waits for healthy (depends_on),
    # then starts scoring + web. discord-bot stays down (compose profile).
    docker compose up -d
    echo "Waiting for health check..."
    for i in $(seq 1 12); do
      sleep 10
      STATUS=$(docker inspect --format='{{.State.Health.Status}}' dcss-game-1 2>/dev/null || echo "unknown")
      if [ "$STATUS" = "healthy" ]; then
        echo "Game container healthy."
        break
      fi
      echo "  Attempt $i/12: $STATUS"
    done
    # Trim buildx cache after a successful build. Cache-bust args (set above)
    # force a fresh upstream fetch every run, leaving multi-GB layers in the
    # cache that nothing else collects. Keep 5 GB of recent layers so
    # incremental no-bust rebuilds stay fast.
    echo "Pruning old buildx cache (keeps 5 GB recent)..."
    docker buildx prune -f --keep-storage=5gb 2>&1 | tail -1 || true
    ;;
  scoring)
    echo "Rebuilding scoring container..."
    docker build -t dcss-scoring -f Dockerfile.scoring .
    docker compose up -d --no-build --no-deps scoring
    ;;
  web|static)
    echo "Restarting nginx..."
    docker compose restart web
    ;;
  config)
    echo "Restarting game (config reload)..."
    docker compose restart game
    ;;
  banner)
    echo "Updating banner (no rebuild)..."
    chmod +x config/startup.sh config/patch-sound.sh
    docker cp config/banner.html dcss-game-1:/app/source/webserver/templates/banner.html
    docker cp config/dgl-banner.txt dcss-game-1:/app/dgl-banner.txt
    docker cp config/dgl-menu-anon.txt dcss-game-1:/app/dgl-menu-anon.txt
    docker cp config/dgl-menu-user.txt dcss-game-1:/app/dgl-menu-user.txt
    docker cp config/dgl-menu-admin.txt dcss-game-1:/app/dgl-menu-admin.txt
    docker cp config/lobby-versions.js dcss-game-1:/app/lobby-versions.js
    docker cp config/dgamelaunch.conf dcss-game-1:/app/dgamelaunch.conf
    docker cp config/default-rc.txt dcss-game-1:/app/default-rc.txt
    docker cp config/startup.sh dcss-game-1:/app/startup.sh
    docker cp config/patch-sound.sh dcss-game-1:/app/patch-sound.sh
    docker compose restart game
    ;;
  all)
    echo "Full rebuild of all services (cache bust enabled)..."
    export TRUNK_CACHE_BUST=$(date +%s)
    export STABLE_CACHE_BUST=$(date +%s)
    docker compose up -d --build
    ;;
  *)
    echo "Usage: deploy.sh [game|scoring|web|config|banner|all]"
    exit 1
    ;;
esac

echo "=== Deploy complete: $(date -u '+%Y-%m-%d %H:%M:%S UTC') ==="
