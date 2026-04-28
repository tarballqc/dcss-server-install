# Customizing your server

Every user-visible string is either templated from `.env` or lives in a single file you can edit.

## Templated from `.env`

Edit `.env`, then `./run.sh banner` (no rebuild). These flow through:

| Variable | Where it shows up |
|---|---|
| `SERVER_ABBR` | Lobby banner, dgamelaunch SSH menu, scoring page titles, browse-page titles, password-reset email |
| `SERVER_URL` | Same — and the `<a href>` for the server name |
| `SERVER_HOST` | Derived from `SERVER_URL` automatically |
| `SERVER_REGION_SHORT` | Lobby latency widget, dgamelaunch banner |
| `SERVER_ADMIN` | "For account or server issues, contact X on Discord" line in lobby + dgamelaunch (omitted if blank) |
| `DISCORD_INVITE` | Password-reset email footer (omitted if blank) |
| `IMPORT_SOURCE_NAME`, `IMPORT_SOURCE_URL`, `IMPORT_DATE` | Registration error message when a player tries to take a name imported from another server |

## Files you'll likely edit

- **`config/banner.html`** — the lobby welcome banner. Tornado template, has `{{ username }}` for logged-in players.
- **`scoring/generate_scores.py`** — search `MOTD` for the lobby card text. Edit, then `./run.sh scoring`.
- **`config/default-rc.txt`** — seeded into every new player's `.rc` file on first login. Sound config, default keys, etc.
- **`config/webtiles-theme.css`** — CSS injected into the WebTiles client (lobby + in-game). Change colors, fonts, etc.
- **`config/games.d/crawl.yaml`** — game modes. Add a Sprint map, reorder, hide a mode. Restart with `./run.sh config`.
- **`config/dgl-banner.txt`, `config/dgl-menu-{anon,user,admin}.txt`** — what SSH players see in dgamelaunch.

## After-the-fact `.env` changes

Most `.env` changes only need `./run.sh banner` (~5 sec):

- `SERVER_ABBR`, `SERVER_URL`, `SERVER_REGION_SHORT`, `SERVER_ADMIN`, `DISCORD_INVITE`
- `IMPORT_SOURCE_*`
- SMTP credentials
- `NOTIFY_EMAIL`

These need a full game rebuild (`./run.sh game`):

- Anything in the `Dockerfile.game` (rare — usually only when adding system packages)
- Switching `DOCKERFILE_GAME=Dockerfile.game.full` (older-versions opt-in)

These need scoring rebuild (`./run.sh scoring`):

- Edits to `scoring/generate_scores.py`

## Sound packs

Loaded directly from the maintainers' canonical hosts at [nemelex.cards](https://nemelex.cards) — no local hosting, full credit to the original authors:

- [**OSP**](https://osp.nemelex.cards/) (Off-Screen Pack) — enabled by default
- [**BindTheEarth**](https://sound-packs.nemelex.cards/Autofire/BindTheEarth/) — enabled by default
- [**DCSS-UST**](https://witchscadence.bandcamp.com/album/dungeon-crawl-stone-soup-ust) (Universal Sound Track, ~110 MB music) composed by **Cass Preston** — commented out by default in `config/default-rc.txt`; uncomment to enable. Please support the composer via his [Bandcamp](https://witchscadence.bandcamp.com/album/dungeon-crawl-stone-soup-ust).

To add or change packs: edit the `sound_pack += ...` lines in `config/default-rc.txt`, then `./run.sh banner`. The DWEM client fetches them from whatever URL you put there.

If you really want to self-host (offline / bandwidth / uptime concerns): drop your zips in a directory served by your nginx, point the `sound_pack += ...` URLs at it, and credit the upstream authors visibly.
