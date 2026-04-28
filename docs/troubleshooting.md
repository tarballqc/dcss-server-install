# Troubleshooting

## Lobby is "stuck on Loading…"

Most often a stale browser cache (DWEM JS module cached from a previous version). Tell the user to hard-refresh (Ctrl+Shift+R / Cmd+Shift+R). If many users report it after a deploy, you can append `?v=N` query strings to the soundpack URLs in `config/default-rc.txt` to force everyone's cache to invalidate, then `./run.sh banner`.

## "Forgot Password" form shows up but emails never arrive

Check `docker compose logs game | grep -i smtp`. Three common causes:

- **No STARTTLS** — upstream WebTiles calls `email_server.login()` directly. Our `patch-sound.sh` injects `starttls()` before it; verify the patch ran (`grep starttls /app/source/webserver/webtiles/util.py` in the container should match).
- **Wrong From address** — SES rejects unverified senders silently. Verify your `SMTP_FROM` domain in the SES console.
- **Sandbox mode** — fresh SES accounts are sandboxed; you can only send to verified recipients. Request production access.

## All logins fail silently

Almost always one of:

- **`libcrypt-dev` missing in the runtime image** — `crypt.crypt()` returns the literal string `*0` for any input. Without `libcrypt-dev`, SHA-512 fails. Our `Dockerfile.game` installs it; verify it's still there if you customized.
- **`crypt_algorithm` not set** — `config/webtiles.py` must have `crypt_algorithm = "6"` (SHA-512). The `startup.sh` DB check warns if a recent password hash is `*0` — that's the symptom.

## SSH (port 222) connects but immediately disconnects

dgamelaunch crashing on startup. Check `docker compose logs game | grep dgamelaunch`. Causes:

- **dgamelaunch compiled without `--enable-sqlite`** — exits with code 106 trying to read flat-file passwd. Our Dockerfile builds with `--enable-sqlite`; confirm if you patched the dgamelaunch build.
- **`/data/dgl-lock` missing** — `startup.sh` `touch`es it; check the volume mount.
- **Bannerfiles missing** — every menu in `dgamelaunch.conf` references a file. If a referenced file doesn't exist, dgamelaunch crashes silently on load. Make sure `dgl-banner.txt` and `dgl-menu-{anon,user,admin}.txt` are all in `/app/`.

## Sound doesn't play

DWEM browser-side issue ~90% of the time. Open devtools → Console. Common errors:

- **`Mismatched anonymous define()`** — RequireJS got hit twice. Caused by a stale cached `dwem-base-loader.js`. Hard-refresh.
- **`Unexpected token 'export'`** — chrome extension noise (not from this server). Filter the console for `chrome-extension://` to confirm it's not yours.
- **Soundpack 404** — the upstream nemelex.cards URL is unreachable (rare) or the URL has changed. Check the URLs in `config/default-rc.txt`; if upstream moved, update them and `./run.sh banner`.

## Frozen builder images got pruned

If you ran `docker image prune -af` (don't), the `dcss-builder-030/031/032/033` images are gone. Symptoms: `docker compose build game` (with `Dockerfile.game.full`) fails with "image dcss-builder-0XX not found".

Fix:

```bash
bash scripts/build-frozen.sh
```

Takes ~45 min. Adds a `keep=true` label so future `prune --filter "label!=keep=true"` won't delete them.

## Tilesheets show wrong sprites after upgrade

The DCSS client URL includes a version hash (`/gamedata/<hash>/`) so tilesheets cache-bust on upgrade. Upstream WebTiles only extracts that hash when `client_path` *isn't* set in config. We always set it (via `games.d/crawl.yaml`), so we patch `process_handler.py` to extract the version anyway (`# DCSS-INSTALL-version-patch`). If you see stale sprites, confirm the patch ran (`grep DCSS-INSTALL-version-patch /app/source/webserver/webtiles/process_handler.py` in the container).

## `/meta/<version>/logfile` returns 404

External aggregators (sequell, dcss-stats) hit those endpoints expecting 200 + maybe-empty body. We pre-create empty `logfile` and `milestones` files in every `/data/saves*` dir at startup so this works even on a brand-new server. If you see 404s, check `docker exec dcss-game-1 ls /data/saves*/logfile`.

## Disk full

```bash
docker exec dcss-game-1 du -sh /data/* | sort -h
```

Usually `/data/morgue` or `/data/ttyrec`. See `docs/upgrading.md` § Disk hygiene for cleanup commands.

## Container won't start after restart

```bash
docker compose logs game --tail=200
```

Read from the bottom up. The first FATAL line is the cause; everything below it is shutdown noise.

## I changed `.env` but nothing changed

`.env` is read at compose-time and at startup-time. Different changes need different deploy modes:

| Change | Mode |
|---|---|
| `SERVER_ABBR`, hostname, banner text, theme, RC defaults | `./run.sh banner` |
| Game modes (`games.d/`) or `webtiles.py` | `./run.sh config` |
| Anything in scoring template | `./run.sh scoring` |
| Anything in `Dockerfile.game` | `./run.sh game` |
