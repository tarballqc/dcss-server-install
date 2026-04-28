#!/bin/bash
set -euo pipefail

# Create all data directories
mkdir -p /data/{saves,saves-0.30,saves-0.31,saves-0.32,saves-0.33,saves-trunk}
mkdir -p /data/{rcfiles,rcfiles-trunk,rcfiles-0.30,rcfiles-0.31,rcfiles-0.32,rcfiles-0.33}
mkdir -p /data/{morgue,ttyrec,sockets/running,logfiles,milestones,logs}

# One-time migration: copy existing RCs to versioned directories
# (existing users had all RCs in /data/rcfiles/)
for rc in /data/rcfiles/*.rc; do
    [ -f "$rc" ] || continue
    base=$(basename "$rc")
    for dir in /data/rcfiles-trunk /data/rcfiles-0.33 /data/rcfiles-0.32 /data/rcfiles-0.31 /data/rcfiles-0.30; do
        [ ! -f "$dir/$base" ] && cp "$rc" "$dir/$base"
    done
done

# Replace server placeholders in banner + SSH dgamelaunch banner
SERVER_ABBR="${SERVER_ABBR:-RGG}"
SERVER_URL="${SERVER_URL:-https://my-server.example.com}"
SERVER_HOST=$(echo "$SERVER_URL" | sed 's|https\?://||')
SERVER_REGION_SHORT="${SERVER_REGION_SHORT:-Your Region}"
OTHER_SERVER_ABBR="${OTHER_SERVER_ABBR:-}"
OTHER_SERVER_URL="${OTHER_SERVER_URL:-}"
OTHER_SERVER_REGION="${OTHER_SERVER_REGION:-}"
sed -i "s/__SERVER_ABBR__/${SERVER_ABBR}/g" /app/source/webserver/templates/banner.html
sed -i "s|__SERVER_URL__|${SERVER_URL}|g" /app/source/webserver/templates/banner.html
sed -i "s|__SERVER_HOST__|${SERVER_HOST}|g" /app/source/webserver/templates/banner.html
sed -i "s|__OTHER_SERVER_ABBR__|${OTHER_SERVER_ABBR}|g" /app/source/webserver/templates/banner.html
sed -i "s|__OTHER_SERVER_URL__|${OTHER_SERVER_URL}|g" /app/source/webserver/templates/banner.html
sed -i "s|__OTHER_SERVER_REGION__|${OTHER_SERVER_REGION}|g" /app/source/webserver/templates/banner.html
# SSH banner + dgamelaunch menus (anon/user/admin all share the same header)
SERVER_ADMIN="${SERVER_ADMIN:-}"
for f in /app/dgl-banner.txt /app/dgl-menu-anon.txt /app/dgl-menu-user.txt /app/dgl-menu-admin.txt; do
    [ -f "$f" ] || continue
    sed -i "s/__SERVER_ABBR__/${SERVER_ABBR}/g" "$f"
    sed -i "s|__SERVER_REGION_SHORT__|${SERVER_REGION_SHORT}|g" "$f"
    sed -i "s|__SERVER_URL__|${SERVER_URL}|g" "$f"
    if [ -n "$SERVER_ADMIN" ]; then
        sed -i "s|__SERVER_ADMIN__|${SERVER_ADMIN}|g" "$f"
    else
        # No admin set — drop the "hosted and maintained by …" phrase entirely.
        sed -i "s| hosted and maintained by __SERVER_ADMIN__\.|.|g; s|__SERVER_ADMIN__||g" "$f"
    fi
done
# WebTiles lobby banner: same admin substitution
if [ -n "$SERVER_ADMIN" ]; then
    sed -i "s|__SERVER_ADMIN__|${SERVER_ADMIN}|g" /app/source/webserver/templates/banner.html
else
    sed -i "s|For account or server issues, contact __SERVER_ADMIN__ on Discord\.||g; s|__SERVER_ADMIN__||g" /app/source/webserver/templates/banner.html
fi
# dgamelaunch config: server_id is shown in SSH menus + logged
[ -f /app/dgamelaunch.conf ] && sed -i "s/__SERVER_ABBR__/${SERVER_ABBR}/g" /app/dgamelaunch.conf

# Patch client.html files (sound, theme, registration, version grouping)
/app/patch-sound.sh

# ── dgamelaunch + SSH setup ────────────────────────────────────────────────
# Persist SSH host keys in /data so players don't get warnings on restart
for ktype in ed25519 rsa; do
    if [ ! -f "/data/ssh_host_${ktype}_key" ]; then
        ssh-keygen -t "$ktype" -f "/data/ssh_host_${ktype}_key" -N "" -q
    fi
    ln -sf "/data/ssh_host_${ktype}_key" "/etc/ssh/ssh_host_${ktype}_key"
    ln -sf "/data/ssh_host_${ktype}_key.pub" "/etc/ssh/ssh_host_${ktype}_key.pub"
done

# dgamelaunch needs these
mkdir -p /dgldir /data/dgl-inprogress/{crawl,sprint,seeded,tut,descent}-{034,trunk,033,032,031,030}
touch /data/dgl-lock
ln -sf /data/passwd.db3 /dgldir/dgamelaunch.db

# Pre-create logfile/milestones in each saves dir so external aggregators
# (sequell, dcss-stats, etc.) don't get 404s before any games have been
# played on a given version. DCSS opens these append-only, so touching
# empty files is safe.
for d in /data/saves /data/saves-trunk /data/saves-0.30 /data/saves-0.31 /data/saves-0.32 /data/saves-0.33; do
    touch "$d/logfile" "$d/milestones"
done

# Fix ownership so crawl user (shed_uid 1001) can write game data
chown -R crawl:crawl /data/saves /data/saves-trunk /data/saves-0.30 /data/saves-0.31 /data/saves-0.32 /data/saves-0.33
chown -R crawl:crawl /data/rcfiles /data/rcfiles-trunk /data/rcfiles-0.30 /data/rcfiles-0.31 /data/rcfiles-0.32 /data/rcfiles-0.33
chown -R crawl:crawl /data/morgue /data/ttyrec /data/sockets /data/dgl-inprogress /data/dgl-lock
chmod 777 /data/sockets /data/sockets/running

/usr/sbin/sshd -D &
echo "[ssh] SSH + dgamelaunch ready on port 22"

# ── Validate passwd.db3 before starting (best-effort — fresh installs OK) ──
python3 << 'DBCHECK'
import os, sqlite3, sys

db = "/data/passwd.db3"
# If you imported users from another server, set DB_MIN_USERS in .env to
# guard against booting with the wrong DB. Default 0 = no minimum.
MIN_USERS = int(os.environ.get("DB_MIN_USERS", "0"))

if not os.path.exists(db):
    print(f"[db-check] {db} doesn't exist yet — fresh install, will be created on first registration.")
    sys.exit(0)

try:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tables = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "dglusers" not in tables:
        print(f"[db-check] {db} has no dglusers table yet (tables: {tables}). Will be created on first registration.")
        sys.exit(0)

    count = c.execute("SELECT COUNT(*) FROM dglusers").fetchone()[0]
    if MIN_USERS and count < MIN_USERS:
        print(f"[db-check] FATAL: {db} has only {count} users (DB_MIN_USERS={MIN_USERS}). Wrong database?", file=sys.stderr)
        sys.exit(1)

    sample = c.execute("SELECT password FROM dglusers ORDER BY id DESC LIMIT 1").fetchone()
    if sample and sample[0] in ("*0", "*1"):
        print(f"[db-check] WARNING: Most recent user has broken hash (*0). Check crypt_algorithm config.", file=sys.stderr)

    # Verify crypt_algorithm is set in config
    import importlib.util
    spec = importlib.util.spec_from_file_location("config", "/app/source/webserver/config.py")
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    algo = getattr(cfg, "crypt_algorithm", None)
    if algo != "6":
        print(f"[db-check] FATAL: crypt_algorithm={algo!r} in config.py (expected '6' for SHA-512)", file=sys.stderr)
        sys.exit(1)

    c.close()
    print(f"[db-check] OK: {count} users, SHA-512 configured, database healthy.")

except sqlite3.DatabaseError as e:
    print(f"[db-check] FATAL: Cannot read {db}: {e}", file=sys.stderr)
    sys.exit(1)
DBCHECK

# Start WebTiles server
exec /app/venv/bin/python3 /app/source/webserver/server.py
