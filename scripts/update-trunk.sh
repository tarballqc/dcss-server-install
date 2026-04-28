#!/bin/bash
# Auto-update DCSS trunk to latest master and stable to latest release tag.
# Only rebuilds when upstream has new changes — skips if already up to date.
# Run via cron: 0 6 * * * /path/to/dcss-server-install/scripts/update-trunk.sh >> /var/log/dcss-trunk-update.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Update check: $(date -u '+%Y-%m-%d %H:%M:%S UTC') ==="

# Pull latest repo changes (Dockerfile, config, etc.)
git pull --quiet

NEEDS_BUILD=false

# --- Check trunk (master) for new commits ---
TRUNK_REMOTE_SHA=$(git ls-remote https://github.com/crawl/crawl.git refs/heads/master | cut -f1)
TRUNK_LOCAL_SHA_FILE="/tmp/dcss-trunk-last-sha"
TRUNK_LOCAL_SHA=""
[ -f "$TRUNK_LOCAL_SHA_FILE" ] && TRUNK_LOCAL_SHA=$(cat "$TRUNK_LOCAL_SHA_FILE")

if [ "$TRUNK_REMOTE_SHA" != "$TRUNK_LOCAL_SHA" ]; then
    echo "Trunk has new commits: ${TRUNK_REMOTE_SHA:0:12} (was: ${TRUNK_LOCAL_SHA:0:12:-none})"
    NEEDS_BUILD=true
else
    echo "Trunk unchanged: ${TRUNK_REMOTE_SHA:0:12}"
fi

# --- Check stable for new release tag ---
STABLE_REMOTE_TAG=$(git ls-remote --tags --sort=-v:refname https://github.com/crawl/crawl.git 'refs/tags/stone_soup-0.34*' | head -1 | sed 's|.*/||')
STABLE_LOCAL_TAG_FILE="/tmp/dcss-stable-last-tag"
STABLE_LOCAL_TAG=""
[ -f "$STABLE_LOCAL_TAG_FILE" ] && STABLE_LOCAL_TAG=$(cat "$STABLE_LOCAL_TAG_FILE")

if [ "$STABLE_REMOTE_TAG" != "$STABLE_LOCAL_TAG" ]; then
    echo "Stable has new tag: $STABLE_REMOTE_TAG (was: ${STABLE_LOCAL_TAG:-none})"
    NEEDS_BUILD=true
else
    echo "Stable unchanged: $STABLE_REMOTE_TAG"
fi

# --- Build only if something changed ---
if [ "$NEEDS_BUILD" = true ]; then
    echo "Building game image..."
    docker compose build --build-arg TRUNK_CACHE_BUST="$(date +%s)" --build-arg STABLE_CACHE_BUST="$(date +%s)" game

    # Restart game container
    docker compose up -d game

    # Save current state
    echo "$TRUNK_REMOTE_SHA" > "$TRUNK_LOCAL_SHA_FILE"
    echo "$STABLE_REMOTE_TAG" > "$STABLE_LOCAL_TAG_FILE"

    echo "=== Update complete: $(date -u '+%Y-%m-%d %H:%M:%S UTC') ==="
else
    echo "=== No changes, skipping build ==="
fi
