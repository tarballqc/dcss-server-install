#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# DCSS Major Version Upgrade Script
# ═══════════════════════════════════════════════════════════════════════════════
# Upgrades the server from current stable to a new major version.
# Freezes the old stable (like 0.30-0.33) and makes the new version active.
#
# Usage (run on the EC2 server):
#   cd /path/to/dcss-server-install && git pull
#   bash scripts/upgrade-stable.sh 0.35
#
# What it does:
#   1. Adds old stable to Dockerfile.frozen + builds frozen image (~15 min)
#   2. Updates all config files (Dockerfile, nginx, games, dgamelaunch, scoring)
#   3. Copies save/RC data so old version keeps working
#   4. Commits, pushes, rebuilds, and deploys (~20 min, ~5 sec downtime)
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
cd "$(dirname "$0")/.."

# Load server identity from .env
if [ -f .env ]; then
    while IFS= read -r line; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        [[ "$line" =~ ^(SERVER_ABBR=|SERVER_URL=) ]] && export "$line"
    done < .env
fi
SERVER_ABBR="${SERVER_ABBR:-MYSRV}"
SERVER_URL="${SERVER_URL:-https://my-server.example.com}"

NEW="${1:?Usage: upgrade-stable.sh <new-version> (e.g. 0.35)}"

# ── Auto-detect current stable from Dockerfile.game ──────────────────────────
OLD=$(grep -oP 'stone_soup-\K0\.\d+' Dockerfile.game | head -1)
OLD_S=$(echo "$OLD" | tr -d '.')    # e.g. "034"
NEW_S=$(echo "$NEW" | tr -d '.')    # e.g. "035"

# For nginx regex: extract the single digit after 0.3 (e.g. "4" from "0.34")
OLD_DIGIT=${OLD#0.3}                # e.g. "4"
NEW_DIGIT=${NEW#0.3}                # e.g. "5"

echo "═══════════════════════════════════════════════════════════"
echo "  DCSS Major Version Upgrade"
echo "  Current stable: $OLD  →  New stable: $NEW"
echo "  $OLD will be frozen (like 0.30-0.33)"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Validation ────────────────────────────────────────────────────────────────
if [ "$OLD" = "$NEW" ]; then
    echo "ERROR: Already on version $NEW"
    exit 1
fi

echo "Checking if branch stone_soup-$NEW exists on GitHub..."
if ! git ls-remote --heads https://github.com/crawl/crawl.git "stone_soup-$NEW" 2>/dev/null | grep -q "stone_soup-$NEW"; then
    echo "ERROR: Branch stone_soup-$NEW not found on github.com/crawl/crawl"
    exit 1
fi
echo "OK — branch exists."
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Dockerfile.frozen — add builder stage for old version
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 1/14: Dockerfile.frozen — adding builder-$OLD_S stage..."

if grep -q "builder-$OLD_S" Dockerfile.frozen; then
    echo "  Already has builder-$OLD_S, skipping."
else
    cat >> Dockerfile.frozen << FEOF

# ─── Build DCSS $OLD ────────────────────────────────────────────────────────
FROM builder-base AS builder-$OLD_S

RUN git clone --depth=1 --branch stone_soup-$OLD \\
    https://github.com/crawl/crawl.git /crawl \\
    && cd /crawl && git submodule update --init --depth=1

WORKDIR /crawl/crawl-ref/source

RUN mv /usr/bin/git /usr/bin/git-real \\
    && CRAWL_VERSION=\$(head -1 /crawl/crawl-ref/docs/changelog.txt | grep -oP '[0-9]+\.[0-9]+(\.[0-9]+)?' || echo "$OLD") \\
    && printf "#!/bin/sh\ncase \"\\\$1\" in describe) echo \"\$CRAWL_VERSION\";; *) exec git-real \"\\\$@\";; esac\n" > /usr/bin/git \\
    && chmod +x /usr/bin/git

RUN make -j1 WEBTILES=y USE_DGAMELAUNCH=y
FEOF
    echo "  Added builder-$OLD_S stage."
fi

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: build-frozen.sh — add old version to loop
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 2/14: build-frozen.sh — adding $OLD_S to version loop..."

if grep -q "$OLD_S" scripts/build-frozen.sh; then
    echo "  Already includes $OLD_S, skipping."
else
    sed -i "s/for ver in \(.*\);/for ver in \1 $OLD_S;/" scripts/build-frozen.sh
    echo "  Added $OLD_S to build loop."
fi

# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Build frozen image for old version (~15 min)
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 3/14: Building frozen image dcss-builder-$OLD_S (~15 min)..."

if docker images --format '{{.Repository}}' | grep -q "dcss-builder-$OLD_S"; then
    echo "  Image dcss-builder-$OLD_S already exists, skipping build."
else
    docker buildx use default 2>/dev/null || true
    docker build \
        --target "builder-$OLD_S" \
        --tag "dcss-builder-$OLD_S" \
        --label "keep=true" \
        -f Dockerfile.frozen \
        .
    echo "  Built dcss-builder-$OLD_S."
fi

# ══════════════════════════════════════════════════════════════════════════════
# STEP 4: Dockerfile.game — update stable branch + add frozen COPY
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 4/14: Dockerfile.game — updating stable to $NEW, adding frozen $OLD..."

# Update stable branch
sed -i "s/stone_soup-$OLD/stone_soup-$NEW/" Dockerfile.game
# Update fallback version string
sed -i "s/|| echo \"$OLD\"/|| echo \"$NEW\"/" Dockerfile.game
# Update comment
sed -i "s/# ─── Build DCSS $OLD (stable)/# ─── Build DCSS $NEW (stable)/" Dockerfile.game
sed -i "s/# Copy $OLD (stable)/# Copy $NEW (stable)/" Dockerfile.game

# Add COPY --from for frozen old version (before the stable COPY block)
if ! grep -q "dcss-builder-$OLD_S" Dockerfile.game; then
    sed -i "/^# Copy $NEW (stable)/i\\
COPY --from=dcss-builder-$OLD_S /crawl/crawl-ref/source/crawl        /app/source-$OLD/crawl\\
COPY --from=dcss-builder-$OLD_S /crawl/crawl-ref/source/dat          /app/source-$OLD/dat\\
COPY --from=dcss-builder-$OLD_S /crawl/crawl-ref/source/webserver    /app/source-$OLD/webserver\\
COPY --from=dcss-builder-$OLD_S /crawl/crawl-ref/docs                /app/source-$OLD/docs\\
" Dockerfile.game
    echo "  Added COPY --from=dcss-builder-$OLD_S block."
fi

# Add old version to RandomTiles.rc loop
sed -i "s|/app/source-trunk/dat|/app/source-trunk/dat /app/source-$OLD/dat|" Dockerfile.game

# Add dgl-play file COPY
sed -i "/dgl-play-$OLD_S.txt/!{/dgl-play-trunk.txt/a\\
COPY config/dgl-play-$NEW_S.txt /app/dgl-play-$NEW_S.txt
}" Dockerfile.game

echo "  Dockerfile.game updated."

# ══════════════════════════════════════════════════════════════════════════════
# STEP 5: config/games.d/crawl.yaml — add template + game entries
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 5/14: crawl.yaml — adding v$OLD_S template, updating stable to $NEW..."

# Add template for old version (before the trunk template)
if ! grep -q "id: v$OLD_S" config/games.d/crawl.yaml; then
    sed -i "/^  - id: trunk$/i\\
  - id: v$OLD_S\\
    crawl_binary: /app/source-$OLD/crawl\\
    client_path: /app/source-$OLD/webserver/game_data/\\
    dir_path: /data/saves-$OLD\\
    rcfile_path: /data/rcfiles-$OLD\\
    macro_path: /data/rcfiles-$OLD\\
    version: \"$OLD\"\\
" config/games.d/crawl.yaml
    echo "  Added v$OLD_S template."
fi

# Update stable template version
sed -i "s/version: \"$OLD\"\$/version: \"$NEW\"/" config/games.d/crawl.yaml

# Update game IDs: rename current stable games to new version
sed -i "s/id: dcss-$OLD/id: dcss-$NEW/" config/games.d/crawl.yaml
sed -i "s/id: tut-$OLD/id: tut-$NEW/" config/games.d/crawl.yaml
sed -i "s/id: sprint-$OLD/id: sprint-$NEW/" config/games.d/crawl.yaml
sed -i "s/id: seeded-$OLD/id: seeded-$NEW/" config/games.d/crawl.yaml
sed -i "s/id: descent-$OLD/id: descent-$NEW/" config/games.d/crawl.yaml

# Update section comment
sed -i "s/# ── Latest stable ($OLD)/# ── Latest stable ($NEW)/" config/games.d/crawl.yaml

# Add frozen old version game entries (before the "Older versions" collapsible section)
# The old stable becomes the first entry in the "Older versions" section
if ! grep -q "id: dcss-$OLD$" config/games.d/crawl.yaml; then
    # Replace the old collapsible separator (on 0.33) with old version block + new separator
    python3 -c "
import re

with open('config/games.d/crawl.yaml') as f:
    content = f.read()

# The 'Older versions' separator is on the first game after trunk section
# We insert the old stable games before it, and move the separator to the old stable's first entry
old_games = '''  # ── Older versions (collapsible via <details> injected through separator) ─
  - id: dcss-$OLD
    template: v$OLD_S
    name: \"DCSS %v\"
    separator: '</span><details class=\"old_versions\" style=\"margin:4px 0\" open><summary style=\"cursor:pointer;color:#5fd7ff;list-style:none;padding:2px 0\">&#9662; Older versions</summary><span><br>'

  - id: tut-$OLD
    template: v$OLD_S
    name: \"Tutorial\"
    options:
      - -tutorial

  - id: sprint-$OLD
    template: v$OLD_S
    name: \"Sprint\"
    options:
      - -sprint

  - id: seeded-$OLD
    template: v$OLD_S
    name: \"Seeded\"
    options:
      - -seed

  - id: descent-$OLD
    template: v$OLD_S
    name: \"Descent\"
    options:
      - -descent

'''

# Remove the old collapsible section header and replace with our new block
content = re.sub(
    r'  # ── Older versions.*\n  - id: dcss-0\.33\n    template: v033\n    name: \"DCSS %v\"\n    separator:.*\n',
    old_games + '  - id: dcss-0.33\n    template: v033\n    name: \"DCSS %v\"\n',
    content
)

with open('config/games.d/crawl.yaml', 'w') as f:
    f.write(content)
"
    echo "  Added frozen $OLD game entries."
fi

echo "  crawl.yaml updated."

# ══════════════════════════════════════════════════════════════════════════════
# STEP 6: config/startup.sh — add directories for old version
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 6/14: startup.sh — adding $OLD directories..."

# Add saves-OLD to mkdir
sed -i "s/saves-trunk}/saves-$OLD,saves-trunk}/" config/startup.sh
# Add rcfiles-OLD to mkdir
sed -i "s/rcfiles-trunk,/rcfiles-$OLD,rcfiles-trunk,/" config/startup.sh
# Add to RC migration loop
sed -i "s|/data/rcfiles-trunk|/data/rcfiles-$OLD /data/rcfiles-trunk|" config/startup.sh
# Add to dgl-inprogress dirs (expand the brace list)
sed -i "s/{$OLD_S,trunk,/{$NEW_S,$OLD_S,trunk,/" config/startup.sh
# Add to chown saves
sed -i "s|chown -R crawl:crawl /data/saves |chown -R crawl:crawl /data/saves /data/saves-$OLD |" config/startup.sh
# Add to chown rcfiles
sed -i "s|chown -R crawl:crawl /data/rcfiles |chown -R crawl:crawl /data/rcfiles /data/rcfiles-$OLD |" config/startup.sh

echo "  startup.sh updated."

# ══════════════════════════════════════════════════════════════════════════════
# STEP 7: config/patch-sound.sh — add old version to patch loops
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 7/14: patch-sound.sh — adding $OLD version paths..."

# Add to STARTTLS patch loop (util.py)
sed -i "s|/app/source-trunk/webserver/webtiles/util.py|/app/source-trunk/webserver/webtiles/util.py /app/source-$OLD/webserver/webtiles/util.py|" config/patch-sound.sh
# Add to registration patch loop (userdb.py)
sed -i "s|/app/source-trunk/webserver/webtiles/userdb.py|/app/source-trunk/webserver/webtiles/userdb.py /app/source-$OLD/webserver/webtiles/userdb.py|" config/patch-sound.sh
# Add patch_client call
sed -i "/patch_client.*source-trunk/a\\
patch_client \"/app/source-$OLD/webserver/templates/client.html\"" config/patch-sound.sh

echo "  patch-sound.sh updated."

# ══════════════════════════════════════════════════════════════════════════════
# STEP 8: nginx/nginx.conf — update meta routes + rcfiles
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 8/14: nginx.conf — updating routing for $NEW stable, $OLD frozen..."

# Expand older-versions regex to include old version digit
sed -i "s/0\\\\.3\[0-$((OLD_DIGIT - 1))\]/0\\\\.3[0-$OLD_DIGIT]/" nginx/nginx.conf

# Replace explicit old stable block with new stable
sed -i "s|location ~ ^/meta/$OLD/|location ~ ^/meta/$NEW/|" nginx/nginx.conf

# Update rcfiles: old stable → versioned path
sed -i "s|location /rcfiles/crawl-$OLD/|location /rcfiles/crawl-$NEW/|" nginx/nginx.conf
sed -i "s|location /rcfiles-json/crawl-$OLD/|location /rcfiles-json/crawl-$NEW/|" nginx/nginx.conf

# Add rcfiles location for frozen old version (before the trunk rcfiles block)
if ! grep -q "rcfiles/crawl-$OLD/" nginx/nginx.conf; then
    sed -i "/location \/rcfiles\/crawl-git\//i\\
        location /rcfiles/crawl-$OLD/ {\\
            alias     /var/www/morgue/rcfiles-$OLD/;\\
            autoindex off;\\
            default_type text/plain;\\
            try_files \$uri /browse-rc.html;\\
        }\\
        location /rcfiles-json/crawl-$OLD/ {\\
            alias     /var/www/morgue/rcfiles-$OLD/;\\
            autoindex on;\\
            autoindex_format json;\\
        }" nginx/nginx.conf
fi

# Update comment
sed -i "s/# Version $OLD:/# Version $NEW:/" nginx/nginx.conf
sed -i "s/# Versions 0.30-0.3$((OLD_DIGIT - 1)):/# Versions 0.30-0.3$OLD_DIGIT:/" nginx/nginx.conf

echo "  nginx.conf updated."

# ══════════════════════════════════════════════════════════════════════════════
# STEP 9: config/dgamelaunch.conf — add menus + game definitions
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 9/14: dgamelaunch.conf — adding $NEW menus, freezing $OLD..."

# Update menu shortcuts: add new version key, shift old stable down
# "p" becomes new stable, old gets a number key
NEXT_KEY=$((OLD_DIGIT + 1))

# In mainmenu_user and mainmenu_admin: change "p" to new, add key for old
for menu_name in mainmenu_user mainmenu_admin; do
    sed -i "/menu\[\"$menu_name\"\]/,/^}/ {
        s/commands\[\"p\"\] = submenu \"play_$OLD_S\"/commands[\"p\"] = submenu \"play_$NEW_S\"/
    }" config/dgamelaunch.conf
    # Insert old version key after the new "p" line
    sed -i "/menu\[\"$menu_name\"\]/,/^}/ {
        /commands\[\"p\"\] = submenu \"play_$NEW_S\"/ a\\
    commands[\"$NEXT_KEY\"] = submenu \"play_$OLD_S\"
    }" config/dgamelaunch.conf
done

# Add new version play menu (copy structure from old stable menu)
if ! grep -q "play_$NEW_S" config/dgamelaunch.conf; then
    sed -i "/^menu\[\"play_$OLD_S\"\]/i\\
menu[\"play_$NEW_S\"] {\\
    bannerfile = \"/app/dgl-play-$NEW_S.txt\"\\
    commands[\"p\"] = play_game \"crawl-$NEW_S\"\\
    commands[\"s\"] = play_game \"sprint-$NEW_S\"\\
    commands[\"d\"] = play_game \"seeded-$NEW_S\"\\
    commands[\"t\"] = play_game \"tut-$NEW_S\"\\
    commands[\"e\"] = play_game \"descent-$NEW_S\"\\
\\
    commands[\"q\"] = submenu \"mainmenu_user\"\\
}\\
" config/dgamelaunch.conf
fi

# Update old stable section comment
sed -i "s/# ── $OLD (stable) ──/# ── $OLD ──/" config/dgamelaunch.conf

# Update old stable game definitions: change binary paths from /app/source/ to /app/source-OLD/
# and save/rc paths from /data/saves to /data/saves-OLD
sed -i "/# ── $OLD ──/,/# ── Trunk ──/ {
    s|/app/source/crawl|/app/source-$OLD/crawl|g
    s|\"-dir\", \"/data/saves\"|\"-dir\", \"/data/saves-$OLD\"|g
    s|\"-rc\", \"/data/rcfiles/|\"-rc\", \"/data/rcfiles-$OLD/|g
    s|\"-macro\", \"/data/rcfiles/|\"-macro\", \"/data/rcfiles-$OLD/|g
    s|rc_fmt = \"/data/rcfiles/|rc_fmt = \"/data/rcfiles-$OLD/|g
    s|rc_template = \"/app/default-rc.txt\"|rc_template = \"/app/default-rc.txt\"|
}" config/dgamelaunch.conf

# Add new stable game definitions (before the trunk section)
if ! grep -q "# ── $NEW (stable) ──" config/dgamelaunch.conf; then
    # Generate the DEFINE blocks for the new stable
    cat > /tmp/new-stable-defs.txt << GEOF

# ── $NEW (stable) ──

DEFINE {
  game_path = "/app/source/crawl"
  game_name = "DCSS $NEW"
  short_name = "crawl-$NEW_S"
  game_args = "/app/source/crawl", "-name", "%n", "-rc", "/data/rcfiles/%n.rc", "-macro", "/data/rcfiles/%n.macro", "-morgue", "/data/morgue/%n", "-dir", "/data/saves"
  rc_template = "/app/default-rc.txt"
  rc_fmt = "/data/rcfiles/%n.rc"
  inprogressdir = "/data/dgl-inprogress/crawl-$NEW_S/"
  ttyrecdir = "/data/ttyrec/%n/"
  encoding = "unicode"
  max_idle_time = 3600
}

DEFINE {
  game_path = "/app/source/crawl"
  game_name = "Sprint $NEW"
  short_name = "sprint-$NEW_S"
  game_args = "/app/source/crawl", "-name", "%n", "-rc", "/data/rcfiles/%n.rc", "-macro", "/data/rcfiles/%n.macro", "-morgue", "/data/morgue/%n", "-dir", "/data/saves", "-sprint"
  rc_template = "/app/default-rc.txt"
  rc_fmt = "/data/rcfiles/%n.rc"
  inprogressdir = "/data/dgl-inprogress/sprint-$NEW_S/"
  ttyrecdir = "/data/ttyrec/%n/"
  encoding = "unicode"
  max_idle_time = 3600
}

DEFINE {
  game_path = "/app/source/crawl"
  game_name = "Seeded $NEW"
  short_name = "seeded-$NEW_S"
  game_args = "/app/source/crawl", "-name", "%n", "-rc", "/data/rcfiles/%n.rc", "-macro", "/data/rcfiles/%n.macro", "-morgue", "/data/morgue/%n", "-dir", "/data/saves", "-seed"
  rc_template = "/app/default-rc.txt"
  rc_fmt = "/data/rcfiles/%n.rc"
  inprogressdir = "/data/dgl-inprogress/seeded-$NEW_S/"
  ttyrecdir = "/data/ttyrec/%n/"
  encoding = "unicode"
  max_idle_time = 3600
}

DEFINE {
  game_path = "/app/source/crawl"
  game_name = "Tutorial $NEW"
  short_name = "tut-$NEW_S"
  game_args = "/app/source/crawl", "-name", "%n", "-rc", "/data/rcfiles/%n.rc", "-macro", "/data/rcfiles/%n.macro", "-morgue", "/data/morgue/%n", "-dir", "/data/saves", "-tutorial"
  rc_template = "/app/default-rc.txt"
  rc_fmt = "/data/rcfiles/%n.rc"
  inprogressdir = "/data/dgl-inprogress/tut-$NEW_S/"
  ttyrecdir = "/data/ttyrec/%n/"
  encoding = "unicode"
  max_idle_time = 3600
}

DEFINE {
  game_path = "/app/source/crawl"
  game_name = "Descent $NEW"
  short_name = "descent-$NEW_S"
  game_args = "/app/source/crawl", "-name", "%n", "-rc", "/data/rcfiles/%n.rc", "-macro", "/data/rcfiles/%n.macro", "-morgue", "/data/morgue/%n", "-dir", "/data/saves", "-descent"
  rc_template = "/app/default-rc.txt"
  rc_fmt = "/data/rcfiles/%n.rc"
  inprogressdir = "/data/dgl-inprogress/descent-$NEW_S/"
  ttyrecdir = "/data/ttyrec/%n/"
  encoding = "unicode"
  max_idle_time = 3600
}
GEOF
    sed -i "/^# ── Game definitions/r /tmp/new-stable-defs.txt" config/dgamelaunch.conf
    rm -f /tmp/new-stable-defs.txt
fi

echo "  dgamelaunch.conf updated."

# ══════════════════════════════════════════════════════════════════════════════
# STEP 10: dgl-play-NNN.txt + dgl-menu-*.txt — create/update banners
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 10/14: DGL banner files..."

# Create play menu for new version
cat > "config/dgl-play-$NEW_S.txt" << MEOF
Logged in as: \$USERNAME

Game selected: Dungeon Crawl Stone Soup $NEW

P)lay Crawl    D) Seeded     S)print    T)utorial
E) Descent

q) Return to main menu
MEOF

# Update dgl-menu-user.txt and dgl-menu-admin.txt
for menu_file in config/dgl-menu-user.txt config/dgl-menu-admin.txt; do
    # Update version line: "P) DCSS 0.34 (stable)" → "P) DCSS 0.35 (stable)"
    sed -i "s/P) DCSS $OLD (stable)/P) DCSS $NEW (stable)/" "$menu_file"
    # Add old version with new key, shift others
    # Replace the version grid
    sed -i "s/${NEXT_KEY}) DCSS 0.3$((OLD_DIGIT - 1))/${NEXT_KEY}) DCSS $OLD             ${NEXT_KEY}) DCSS 0.3$((OLD_DIGIT - 1))/" "$menu_file" 2>/dev/null || true
    # Simpler approach: regenerate the version grid
    python3 -c "
with open('$menu_file') as f:
    lines = f.readlines()

# Find and replace the version grid (lines with 'DCSS 0.3')
new_lines = []
skip_grid = False
grid_done = False
for line in lines:
    if 'P) DCSS' in line and not grid_done:
        skip_grid = True
        # Generate new grid
        versions = [('P', '$NEW', '(stable)'), ('T', 'trunk', '')]
        old_vers = []
        # Add old stable + existing frozen versions
        for v in ['$OLD', '0.33', '0.32', '0.31', '0.30']:
            d = v.replace('0.', '')
            key = str(int(d) - 30 + $NEXT_KEY - int('$OLD_DIGIT'))
            # Use sequential keys: OLD_DIGIT+1, then 3, 2, 1, 0
            old_vers.append((v, d))

        new_lines.append('P) DCSS $NEW (stable)    T) DCSS trunk\n')
        # Pair up old versions
        pairs = old_vers
        for i in range(0, len(pairs), 2):
            left_v, left_d = pairs[i]
            left_key = str(int(left_d) - 30)
            left = f'{left_key}) DCSS {left_v}'
            if i + 1 < len(pairs):
                right_v, right_d = pairs[i+1]
                right_key = str(int(right_d) - 30)
                right = f'{right_key}) DCSS {right_v}'
                new_lines.append(f'{left:<25}{right}\n')
            else:
                new_lines.append(f'{left}\n')
        grid_done = True
        continue
    if skip_grid:
        if line.strip() == '' or ('DCSS' in line and ')' in line):
            continue
        else:
            skip_grid = False
    new_lines.append(line)

with open('$menu_file', 'w') as f:
    f.writelines(new_lines)
"
done

echo "  DGL banner files updated."

# ══════════════════════════════════════════════════════════════════════════════
# STEP 11: scoring/generate_scores.py — update save dirs + nav links
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 11/14: scoring/generate_scores.py — updating version references..."

# Update the ALL_SAVE_DIRS tuple: rename current stable label, add old version entry
sed -i "s|(\"\/data\/saves\",       \"$OLD\")|(\"/data/saves\",       \"$NEW\")|" scoring/generate_scores.py
# Add old version save dir after the trunk entry
sed -i "/\"\/data\/saves-trunk\", \"trunk\"/a\\
    (\"/data/saves-$OLD\",  \"$OLD\")," scoring/generate_scores.py
# Update RC file nav links
sed -i "s|/rcfiles/crawl-$OLD/|/rcfiles/crawl-$NEW/|g" scoring/generate_scores.py

echo "  generate_scores.py updated."

# ══════════════════════════════════════════════════════════════════════════════
# STEP 12: scripts/daily-report.py — update save dir paths
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 12/14: daily-report.py — updating save paths..."

if [ -f scripts/daily-report.py ]; then
    # The stable saves entry "/data/saves/logfile" stays (it's now 0.35)
    # Add old version saves dir after trunk
    if ! grep -q "saves-$OLD" scripts/daily-report.py; then
        sed -i "/\"\/data\/saves-trunk\/logfile\"/a\\
    \"/data/saves-$OLD/logfile\"," scripts/daily-report.py
    fi
    echo "  daily-report.py updated."
else
    echo "  daily-report.py not found, skipping."
fi

# ══════════════════════════════════════════════════════════════════════════════
# STEP 13: Migrate data (copy saves + RCs for old version)
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 13/14: Migrating data (copying saves + RCs for $OLD)..."

# Copy inside the running container
docker exec dcss-game-1 bash -c "
    if [ ! -d /data/saves-$OLD ]; then
        echo '  Copying /data/saves → /data/saves-$OLD...'
        cp -a /data/saves /data/saves-$OLD
        echo '  Done.'
    else
        echo '  /data/saves-$OLD already exists, skipping.'
    fi

    if [ ! -d /data/rcfiles-$OLD ]; then
        echo '  Copying /data/rcfiles → /data/rcfiles-$OLD...'
        cp -a /data/rcfiles /data/rcfiles-$OLD
        echo '  Done.'
    else
        echo '  /data/rcfiles-$OLD already exists, skipping.'
    fi

    chown -R crawl:crawl /data/saves-$OLD /data/rcfiles-$OLD
"

echo "  Data migration complete."

# ══════════════════════════════════════════════════════════════════════════════
# STEP 14: Commit, push, rebuild, deploy
# ══════════════════════════════════════════════════════════════════════════════
echo "Step 14/14: Committing, building, and deploying..."

git add -A
git commit -m "feat: upgrade stable $OLD → $NEW, freeze $OLD as older version

- Dockerfile.frozen: added builder-$OLD_S stage
- Dockerfile.game: stable now builds stone_soup-$NEW
- crawl.yaml: $NEW is latest, $OLD moved to older versions
- dgamelaunch.conf: added $NEW menus and game definitions
- nginx.conf: updated routing for $NEW stable
- startup.sh: added $OLD data directories
- scoring: added $OLD save dir, updated nav links
- Data: copied saves + rcfiles for $OLD frozen version"

git push origin main 2>/dev/null || true
git push origin main 2>/dev/null || true

echo ""
echo "Building game container with $NEW stable (~20 min)..."
docker compose build --build-arg TRUNK_CACHE_BUST="$(date +%s)" game

echo ""
echo "Deploying... (~5 sec downtime)"
docker compose up -d game

# Wait for healthy
echo "Waiting for health check..."
for i in $(seq 1 12); do
    sleep 10
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' dcss-game-1 2>/dev/null || echo "unknown")
    if [ "$STATUS" = "healthy" ]; then
        echo "Container is healthy!"
        break
    fi
    echo "  Health check $i/12: $STATUS"
done

# Update release check state file
LATEST_TAG=$(git ls-remote --tags https://github.com/crawl/crawl.git "refs/tags/${NEW}.*" 2>/dev/null \
    | grep -v '\^{}' | sed 's|.*/||' | grep -E '^0\.[0-9]+\.[0-9]+$' | sort -V | tail -1 || echo "${NEW}.0")
echo "$LATEST_TAG" > .stable-last-tag

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Upgrade complete!"
echo "  $NEW is now the stable version"
echo "  $OLD is frozen alongside 0.30-0.33"
echo "  Verify at: ${SERVER_URL:-https://my-server.example.com}"
echo "═══════════════════════════════════════════════════════════"
