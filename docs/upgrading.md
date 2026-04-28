# Upgrading & maintenance

## Auto-detected new releases

`scripts/check-releases.sh` runs twice a day (cron — you set it up) and rebuilds when:

- Trunk has new commits since the last successful build
- A new stable point release has been tagged on the current stable branch
- A new major version (e.g. 0.35) has dropped — *only emails you*; you decide whether to run `scripts/upgrade-stable.sh 0.35`

To install the cron:

```bash
( crontab -l 2>/dev/null; echo "0 6,21 * * * /full/path/to/dcss-server-install/scripts/check-releases.sh >> /var/log/dcss-release-check.log 2>&1" ) | crontab -
```

Set `NOTIFY_EMAIL` in `.env` to get success/failure emails.

## Trunk-only quick refresh

If you don't want the full release-checker but want to pull trunk daily:

```bash
( crontab -l 2>/dev/null; echo "0 4 * * * /full/path/to/dcss-server-install/scripts/update-trunk.sh >> /var/log/dcss-trunk-update.log 2>&1" ) | crontab -
```

## Manual rebuild

```bash
cd ~/dcss
git pull                  # pull repo updates (this installer)
./run.sh game             # rebuild image + restart, ~20 min, ~5 sec downtime
```

The `STABLE_CACHE_BUST` and `TRUNK_CACHE_BUST` build args are set to `$(date +%s)` by `deploy.sh game`, so the upstream `git clone` re-fetches even when nothing else in the Dockerfile changed.

## Major version upgrade (e.g. 0.34 → 0.35)

When a new major drops upstream:

```bash
bash scripts/upgrade-stable.sh 0.35
```

This freezes 0.34 (so anyone with a 0.34 save can keep playing) and makes 0.35 the active stable. Takes ~30 min total. Read the script before running — it edits Dockerfiles, games.d, nginx, and commits.

## Adding older versions (0.30–0.33)

Off by default. To enable:

1. Build the frozen images once (~45 min):
   ```bash
   bash scripts/build-frozen.sh
   ```
2. Switch the build to the multi-version Dockerfile:
   ```bash
   echo "DOCKERFILE_GAME=Dockerfile.game.full" >> .env
   cp config/games.d/crawl.yaml.full config/games.d/crawl.yaml
   ```
3. Rebuild:
   ```bash
   ./run.sh game
   ```

Frozen images are tagged with `keep=true` so `docker image prune` won't delete them, but **never** run `docker image prune -af` — that ignores labels and will require rebuilding from scratch.

## Custom version compilation

`scripts/build-frozen.sh` shows the pattern. Copy it, point at any DCSS branch or tag, set the image name, build. Then add a `COPY --from=<image> ...` block to `Dockerfile.game.full` and a stanza to `config/games.d/crawl.yaml.full`.

## Disk hygiene

Saves and morgues live forever in `/var/lib/docker/volumes/dcss_game-data/_data/`. Common cleanup:

```bash
# Old morgues (>1 year) — keep saves
docker exec dcss-game-1 find /data/morgue -type f -mtime +365 -delete
# Old ttyrecs (>180 days)
docker exec dcss-game-1 find /data/ttyrec -type f -mtime +180 -delete
```

The DB and active saves are tiny — the bulk is morgues + ttyrecs.

## Backups

The thing you actually need to back up:

```
/var/lib/docker/volumes/dcss_game-data/_data/passwd.db3
```

Saves and morgues are nice-to-have; `passwd.db3` is the user database (and *only* lives in this volume). Snapshot the volume daily:

```bash
docker run --rm -v dcss_game-data:/data:ro -v "$PWD":/backup alpine \
    tar czf /backup/passwd-$(date +%F).tar.gz -C /data passwd.db3
```
