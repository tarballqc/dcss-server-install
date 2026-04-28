#!/bin/bash
# Patch client.html with DWEM sound support, theme CSS, hub registration, etc.
# Called at container startup before the WebTiles server starts.
# Patches both stable and trunk client.html files.
set -euo pipefail

patch_client() {
    local CLIENT_HTML="$1"

    if [ ! -f "$CLIENT_HTML" ]; then
        echo "[patch] $CLIENT_HTML not found, skipping."
        return
    fi

    echo "[patch] Processing $CLIENT_HTML"

    # ── DWEM sound support (replaces require.js script tag) ──────────────────
    # DWEM must be the sole loader of RequireJS to avoid race conditions.
    # We REPLACE the original require.js script tag with the DWEM block.
    # DWEM's fallback detects require.js is missing and loads it itself,
    # giving it full control over RequireJS initialization.
    # NOTE: insert-before approach was tested 2026-03-22 and broke the lobby.
    local MARKER="<!-- DWEM-SOUND"

    if ! grep -q "$MARKER" "$CLIENT_HTML" 2>/dev/null; then
        if [ -f /app/dwem-inject.html ] && [ -d /app/source/webserver/static/dwem ]; then
            local TMPFILE_DWEM
            TMPFILE_DWEM=$(mktemp)
            awk '
            /require\.js.*data-main/ {
                while ((getline line < "/app/dwem-inject.html") > 0) print line
                next
            }
            { print }
            ' "$CLIENT_HTML" > "$TMPFILE_DWEM"
            mv "$TMPFILE_DWEM" "$CLIENT_HTML"
            echo "[sound-patch] Replaced require.js with DWEM sound support."
        else
            echo "[sound-patch] DWEM files not found, skipping."
        fi
    else
        echo "[sound-patch] Already patched, skipping."
    fi

    # ── Dungeon Gate theme CSS ──────────────────────────────────────────────
    local THEME_MARKER="<!-- DUNGEON-GATE-THEME -->"
    local THEME_CSS="/app/webtiles-theme.css"

    if ! grep -q "$THEME_MARKER" "$CLIENT_HTML" 2>/dev/null; then
        if [ -f "$THEME_CSS" ]; then
            local CSS_CONTENT
            CSS_CONTENT=$(cat "$THEME_CSS")
            local TMPFILE
            TMPFILE=$(mktemp)
            awk -v marker="$THEME_MARKER" -v css="$CSS_CONTENT" '
            /<\/head>/ {
                print marker
                print "<style>"
                print css
                print "</style>"
            }
            { print }
            ' "$CLIENT_HTML" > "$TMPFILE"
            mv "$TMPFILE" "$CLIENT_HTML"
            echo "[theme-patch] Injected Dungeon Gate theme into $CLIENT_HTML."
        else
            echo "[theme-patch] WARNING: $THEME_CSS not found, skipping theme injection."
        fi
    else
        echo "[theme-patch] Already patched, skipping."
    fi

    # ── Embed detection script ──────────────────────────────────────────────
    local EMBED_MARKER="<!-- EMBED-DETECT -->"

    if ! grep -q "$EMBED_MARKER" "$CLIENT_HTML" 2>/dev/null; then
        sed -i "s|</head>|$EMBED_MARKER\n<script>if(new URLSearchParams(location.search).has('embed'))document.body.classList.add('embed');</script>\n</head>|" "$CLIENT_HTML"
        echo "[embed-patch] Injected embed detection into $CLIENT_HTML."
    else
        echo "[embed-patch] Already patched, skipping."
    fi

    # ── Viewport fix (replace fixed 860px with responsive) ─────────────
    if grep -q 'width=860' "$CLIENT_HTML" 2>/dev/null; then
        sed -i 's/width=860/width=device-width/' "$CLIENT_HTML"
        echo "[viewport-patch] Fixed viewport to device-width in $CLIENT_HTML."
    fi

    # ── Lobby version grouping (collapsible older versions) ───────────────
    local LOBBY_MARKER="<!-- LOBBY-VERSIONS -->"

    if ! grep -q "$LOBBY_MARKER" "$CLIENT_HTML" 2>/dev/null; then
        local LOBBY_JS
        LOBBY_JS=$(cat /app/lobby-versions.js 2>/dev/null || echo '')
        if [ -n "$LOBBY_JS" ]; then
            local TMPFILE3
            TMPFILE3=$(mktemp)
            awk -v marker="$LOBBY_MARKER" '
            /<\/head>/ {
                print marker
                print "<script>"
                while ((getline line < "/app/lobby-versions.js") > 0) print line
                print "</script>"
            }
            { print }
            ' "$CLIENT_HTML" > "$TMPFILE3"
            mv "$TMPFILE3" "$CLIENT_HTML"
            echo "[lobby-patch] Injected version grouping into $CLIENT_HTML."
        else
            echo "[lobby-patch] WARNING: /app/lobby-versions.js not found, skipping."
        fi
    else
        echo "[lobby-patch] Already patched, skipping."
    fi
}

# ── Patch version hash for tile cache busting ─────────────────────────────
# The crawl binary sends its version to the webserver via a client_path message.
# But upstream code only reads the version when client_path is NOT set in config.
# In DGL mode (where client_path is always set in games.d/crawl.yaml), the version
# is never extracted, making the /gamedata/<hash>/ URL static across rebuilds.
# This causes stale tilesheets (wrong species/weapon sprites) after server updates.
# Fix: also extract crawl_version when client_path was already set from config.
for procpy in /app/source/webserver/webtiles/process_handler.py /app/source-trunk/webserver/webtiles/process_handler.py \
              /app/source-0.33/webserver/webtiles/process_handler.py /app/source-0.32/webserver/webtiles/process_handler.py \
              /app/source-0.31/webserver/webtiles/process_handler.py /app/source-0.30/webserver/webtiles/process_handler.py; do
    if [ -f "$procpy" ] && ! grep -q 'DCSS-INSTALL-version-patch' "$procpy" 2>/dev/null; then
        # The upstream pattern:
        #   if msgobj["msg"] == "client_path":
        #       if self.client_path == None:
        #           self.client_path = ...
        #           if "version" in msgobj:
        #               self.crawl_version = msgobj["version"]
        #           self.send_client_to_all()
        #
        # We add an else branch: when client_path is already set (from config),
        # still extract the version and re-send the client with the updated hash.
        python3 -c "
import re, sys

with open('$procpy', 'r') as f:
    content = f.read()

# Find the block that handles client_path messages and add an else branch
# to extract version even when client_path is already set from config.
old = '''            if msgobj[\"msg\"] == \"client_path\":
                if self.client_path == None:'''

new = '''            if msgobj[\"msg\"] == \"client_path\":  # DCSS-INSTALL-version-patch
                if self.client_path == None:'''

if old in content:
    content = content.replace(old, new, 1)

    # Now find the send_client_to_all() call and add an else branch after it
    # Look for the pattern ending with send_client_to_all() inside the client_path block
    old_block = '''                    self.send_client_to_all()
            elif msgobj[\"msg\"] == \"flush_messages\":'''

    new_block = '''                    self.send_client_to_all()
                else:
                    # client_path already set from config; still extract version
                    if \"version\" in msgobj:
                        self.crawl_version = msgobj[\"version\"]
                        self.logger.info(\"Crawl version (from binary): %s.\", self.crawl_version)
                        self.send_client_to_all()
            elif msgobj[\"msg\"] == \"flush_messages\":'''

    if old_block in content:
        content = content.replace(old_block, new_block, 1)
        with open('$procpy', 'w') as f:
            f.write(content)
        print('[version-patch] Patched $procpy')
    else:
        print('[version-patch] Could not find send_client_to_all block in $procpy', file=sys.stderr)
else:
    print('[version-patch] Could not find client_path handler in $procpy', file=sys.stderr)
"
    else
        echo "[version-patch] Already patched or not found: $procpy"
    fi
done

# ── Patch password reset email template ─────────────────────────────────
python3 /app/patch-email-template.py

# ── Patch transparent password re-hashing (DES → SHA-512 on login) ──────
python3 /app/patch-rehash.py

# ── Patch SMTP to support STARTTLS (required by AWS SES on port 587) ───
for utilpy in /app/source/webserver/webtiles/util.py /app/source-trunk/webserver/webtiles/util.py \
              /app/source-0.33/webserver/webtiles/util.py /app/source-0.32/webserver/webtiles/util.py \
              /app/source-0.31/webserver/webtiles/util.py /app/source-0.30/webserver/webtiles/util.py; do
    if [ -f "$utilpy" ] && ! grep -q 'starttls' "$utilpy" 2>/dev/null; then
        sed -i '/email_server.login/i\            email_server.starttls()' "$utilpy"
        echo "[smtp-patch] Added STARTTLS to $utilpy"
    fi
done

# ── Patch registration "user already exists" message ───────────────────
# Only runs when IMPORT_SOURCE_NAME is set (i.e. you imported accounts
# from another DCSS server and want to tell people they may already
# have an account).
if [ -n "${IMPORT_SOURCE_NAME:-}" ]; then
    SERVER_ABBR_REG="${SERVER_ABBR:-MYSRV}"
    IMPORT_SOURCE_URL="${IMPORT_SOURCE_URL:-}"
    IMPORT_DATE="${IMPORT_DATE:-recently}"
    REG_MSG="This username is already registered. ${SERVER_ABBR_REG} imported accounts from ${IMPORT_SOURCE_NAME} (${IMPORT_SOURCE_URL}) on ${IMPORT_DATE}. If this is your account, try logging in with your ${IMPORT_SOURCE_NAME} password or use Forgot Password to reset it."
    for userdb in /app/source/webserver/webtiles/userdb.py /app/source-trunk/webserver/webtiles/userdb.py \
                  /app/source-0.33/webserver/webtiles/userdb.py /app/source-0.32/webserver/webtiles/userdb.py \
                  /app/source-0.31/webserver/webtiles/userdb.py /app/source-0.30/webserver/webtiles/userdb.py; do
        [ -f "$userdb" ] || continue
        # Idempotent: replace either the original WebTiles text OR any prior patched version
        # of the message (so re-patching with new IMPORT_* env vars rewrites it correctly).
        if grep -q 'User already exists!' "$userdb" 2>/dev/null; then
            sed -i "s|User already exists!|${REG_MSG}|" "$userdb"
            echo "[reg-patch] Patched fresh registration message in $userdb"
        elif grep -q 'This username is already registered\. .* imported accounts from' "$userdb" 2>/dev/null; then
            python3 - "$userdb" <<PY
import re, sys
path = sys.argv[1]
new_msg = """${REG_MSG}"""
with open(path) as f:
    content = f.read()
content2 = re.sub(
    r'This username is already registered\. [^"]*?Forgot Password to reset it\.',
    new_msg,
    content,
)
if content != content2:
    with open(path, "w") as f:
        f.write(content2)
    print(f"[reg-patch] Re-patched existing registration message in {path}")
PY
        fi
    done
fi

# ── Replace | separator with · in game mode links ────────────────────
for gamelinks in /app/source/webserver/templates/game_links.html /app/source-trunk/webserver/templates/game_links.html \
                 /app/source-0.33/webserver/templates/game_links.html /app/source-0.32/webserver/templates/game_links.html \
                 /app/source-0.31/webserver/templates/game_links.html /app/source-0.30/webserver/templates/game_links.html; do
    if [ -f "$gamelinks" ] && grep -q ' | ' "$gamelinks" 2>/dev/null; then
        sed -i 's/ | / \&middot; /g' "$gamelinks"
        echo "[separator-patch] Replaced | with · in $gamelinks"
    fi
done

# Patch all versions
patch_client "/app/source/webserver/templates/client.html"
patch_client "/app/source-trunk/webserver/templates/client.html"
patch_client "/app/source-0.30/webserver/templates/client.html"
patch_client "/app/source-0.31/webserver/templates/client.html"
patch_client "/app/source-0.32/webserver/templates/client.html"
patch_client "/app/source-0.33/webserver/templates/client.html"
