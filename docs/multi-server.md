# Multi-server pattern

This repo is designed so the same code can run any number of DCSS servers, each with its own identity. Per-server differences live entirely in `.env`. The code stays identical.

## How

Every user-visible string is one of:

- **`__SERVER_ABBR__`** — the 3–6 letter server name (e.g. `CAO`, `CKO`)
- **`__SERVER_URL__`** — full base URL with scheme (`https://crawl.example.com`)
- **`__SERVER_HOST__`** — derived from URL (`crawl.example.com`)
- **`__SERVER_REGION_SHORT__`** — region label (`Eastern US`)
- **`__SERVER_ADMIN__`** — optional admin handle (omitted in output if blank)

These are substituted at one of three points:

1. **Image build time** — N/A. Nothing is baked in.
2. **Container startup** (`config/startup.sh`) — for files inside the game container: `banner.html`, `dgl-banner.txt`, `dgl-menu-*.txt`, `dgamelaunch.conf`, `default-rc.txt`.
3. **Host deploy time** (`scripts/deploy.sh` render step) — for files served by the host-mounted nginx: `nginx/html/*.template` → `nginx/html/*` (gitignored renders).
4. **Module load** (`scoring/generate_scores.py`) — `_apply_server_branding(...)` rewrites the three baked HTML templates at process start.
5. **Patch time** (`config/patch-email-template.py`) — reads `SERVER_*` from env, bakes them into the userdb.py email body. Idempotent: re-running with new `.env` re-skins the email.

## Adding a second server

```bash
# On a second box
git clone https://github.com/tarballqc/dcss-server-install ~/dcss
cd ~/dcss
./install.sh        # different SERVER_ABBR, hostname, region
./run.sh game
```

Same code, different `.env`. That's it.

## Linking two servers in the lobby

Optional — show a latency badge for the *other* server in your lobby banner with a "play there" link. Set in `.env`:

```env
OTHER_SERVER_NAME=CRG
OTHER_SERVER_URL=https://crawl-west.example.com
OTHER_SERVER_REGION=US-West
```

Then edit `config/banner.html` to re-add the cross-server `<span id="rgg-other-server">` (we removed it from this repo's default banner, but the JS in `nginx/html/banner-stats.js` still supports it — see git history for the original markup).

## Sharing accounts across servers

If you want players to sign up once and play on all your servers:

1. Pick one server's `passwd.db3` as canonical.
2. Periodically rsync it to the other servers (read-only mount or hot copy).
3. Or set up a shared SQLite over a network mount (NFS / EFS).

The community-historical pattern is to **share the dgamelaunch SSH key** ("CAO key") so players can SSH-roam without re-authenticating, but each server keeps its own user DB. Up to you.
