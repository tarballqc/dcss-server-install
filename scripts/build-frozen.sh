#!/bin/bash
# Build frozen DCSS versions (0.30-0.33) as locally tagged images.
# Run once per server, or after a docker system prune.
# These images are referenced by Dockerfile.game via COPY --from.

set -e

cd "$(dirname "$0")/.."

# Ensure we're using the default docker builder (not docker-container)
docker buildx use default 2>/dev/null || true

for ver in 030 031 032 033; do
    tag="dcss-builder-${ver}"
    echo "=== Building ${tag} ==="
    docker build \
        --no-cache \
        --target "builder-${ver}" \
        --tag "${tag}" \
        --label "keep=true" \
        -f Dockerfile.frozen \
        .
    echo "=== ${tag} done ==="
    echo
done

echo "All frozen versions built:"
docker images --filter "label=keep=true" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"
