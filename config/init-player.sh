#!/bin/bash
# Called by WebTiles when a new user registers.
# Arguments: $1 = username
USERNAME="$1"
mkdir -p "/data/morgue/$USERNAME"
mkdir -p "/data/ttyrec/$USERNAME"

# Create RC directories for all versions and copy default RC
for RCDIR in /data/rcfiles /data/rcfiles-trunk /data/rcfiles-0.33 /data/rcfiles-0.32 /data/rcfiles-0.31 /data/rcfiles-0.30; do
    mkdir -p "$RCDIR"
    RC_FILE="$RCDIR/$USERNAME.rc"
    if [ ! -f "$RC_FILE" ] && [ -f /app/default-rc.txt ]; then
        cp /app/default-rc.txt "$RC_FILE"
    fi
done

# Create save directories
mkdir -p /data/saves /data/saves-trunk /data/saves-0.33 /data/saves-0.32 /data/saves-0.31 /data/saves-0.30
