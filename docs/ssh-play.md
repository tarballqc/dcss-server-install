# SSH play (dgamelaunch)

Players who don't want a browser can SSH in and play in-terminal:

```bash
ssh -p 222 crawl@your-host
```

The default password is `crawl`. Once they're in, dgamelaunch shows a menu where they can register, log in, and pick a game (version + mode).

## How it works

- The game container runs `sshd` on port 22 internally; docker-compose maps host port **222** to it.
- The SSH user is `crawl` (uid 1001) with shell `/usr/local/sbin/dgamelaunch`.
- dgamelaunch is compiled with `--enable-sqlite` so it shares **the same `passwd.db3`** as WebTiles. Login once, play either way.
- Saves are also shared (`/data/saves*`) — players can switch between SSH and browser **mid-game**.

## CAO key (optional, key auth)

The historic DCSS community uses a shared SSH key (the "CAO key") so players can roam between servers. If you want to support that:

1. Drop the public half of `cao_key.pub` into the image (extend `Dockerfile.game` with a `COPY cao_key.pub /home/crawl/.ssh/authorized_keys`).
2. Players use `ssh -p 222 -i cao_key crawl@your-host` (no password prompt).

For a brand-new server with no inherited userbase, this is optional — the password `crawl` is enough.

## Customizing the SSH banner

`config/dgl-banner.txt` is what players see *before* login. `config/dgl-menu-{anon,user,admin}.txt` are the menus shown after login (anonymous users, logged-in players, admins). All four use `__SERVER_ABBR__` / `__SERVER_REGION_SHORT__` / `__SERVER_URL__` / `__SERVER_ADMIN__` placeholders that startup substitutes from `.env`.

Edit any of them, `./run.sh banner`, done. ~5 sec downtime.

## Why dgamelaunch can break silently

Three failure modes worth knowing:

1. **Compiled without `--enable-sqlite`**: dgamelaunch tries to read flat-file passwd, can't, exits with code 106. Symptom: SSH connects, immediately disconnects with no message.
2. **`/data/dgl-lock` missing**: dgamelaunch exits without writing to a log. `startup.sh` already creates it.
3. **Bannerfiles missing**: dgamelaunch.conf must reference existing files for every menu. Missing → silent crash on load.

The Dockerfile + startup.sh handle all three correctly out of the box. If you customize, keep them in mind.
