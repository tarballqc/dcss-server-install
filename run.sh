#!/usr/bin/env bash
# run.sh — convenience wrapper for scripts/deploy.sh
# Usage: ./run.sh [game|scoring|web|config|banner]
set -euo pipefail
cd "$(dirname "$0")"
exec bash scripts/deploy.sh "$@"
