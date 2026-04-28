#!/usr/bin/env python3
"""
DCSS WebTiles Discord Bot — my-server.example.com

Full-featured Discord bot for Dungeon Crawl Stone Soup.

Features:
  - Slash commands: /stats, /leaderboard, /records, /morgue, /info
  - New player registration alerts (watches passwd.db3)
  - Win celebrations with records, achievements & streaks
  - Death notifications with flavor text & context
  - Milestone tracking (runes, orb, branches, gods, uniques)
  - Server records (highest score, fastest win, combo firsts)
  - Historical scan on startup for complete stats
  - Daily activity digest at midnight UTC
  - Bot presence showing live activity
  - All 6 game versions monitored (0.30-0.34, trunk)
"""

import json
import logging
import os
import random
import re
import secrets
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

# ═══════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("dcss-bot")

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

BOT_TOKEN         = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID        = int(os.environ.get("DISCORD_CHANNEL_ID") or "0")
GUILD_ID          = int(os.environ.get("DISCORD_GUILD_ID") or "0") or None
POLL_INTERVAL     = int(os.environ.get("POLL_INTERVAL", "5"))
STATE_FILE        = os.environ.get("STATE_FILE", "/data/discord-bot-state.json")
SERVER_URL        = os.environ.get("SERVER_URL", "https://my-server.example.com")
SERVER_NAME       = os.environ.get("SERVER_NAME", "MYSRV")
SERVER_HOST       = SERVER_URL.replace("https://", "").replace("http://", "").rstrip("/")
SERVER_REGION     = os.environ.get("SERVER_REGION", "")
DISCORD_INVITE    = os.environ.get("DISCORD_INVITE", "")
IS_PRIMARY_BOT    = os.environ.get("IS_PRIMARY_BOT", "1").strip().lower() not in ("0", "false", "no", "")
OTHER_SERVER_URL  = os.environ.get("OTHER_SERVER_URL", "").rstrip("/")
OTHER_SERVER_NAME = os.environ.get("OTHER_SERVER_NAME", "").strip()
SERVER_SLUG       = SERVER_NAME.lower()
OTHER_SERVER_SLUG = OTHER_SERVER_NAME.lower() if OTHER_SERVER_NAME else ""
PASSWD_DB         = os.environ.get("PASSWD_DB", "/data/passwd.db3")
DEATH_MIN_XL      = int(os.environ.get("DEATH_MIN_XL", "1"))
REG_POLL_INTERVAL = int(os.environ.get("REG_POLL_INTERVAL", "30"))

DISCORD_LINKS_FILE = os.environ.get("DISCORD_LINKS_FILE", "/data/discord-links.json")
ROLE_STATE_FILE    = os.environ.get("ROLE_STATE_FILE", "/data/dcss-role-state.json")
ROLE_ANNOUNCE_CHANNEL = os.environ.get("ROLE_ANNOUNCE_CHANNEL", "1482839419416215553")
ROLE_GUIDE_CHANNEL    = os.environ.get("ROLE_GUIDE_CHANNEL", "1486160370786893996")
ROLE_RESYNC_MINUTES   = int(os.environ.get("ROLE_RESYNC_MINUTES", "60"))

STATE_VERSION = 3  # Bump to force state reset and full rescan

# Monitored game versions — all 6
VERSION_DIRS = [
    ("/data/saves",       "0.34"),
    ("/data/saves-trunk", "trunk"),
    ("/data/saves-0.33",  "0.33"),
    ("/data/saves-0.32",  "0.32"),
    ("/data/saves-0.31",  "0.31"),
    ("/data/saves-0.30",  "0.30"),
]

WATCH_FILES = ["logfile", "milestones"]

# ═══════════════════════════════════════════════════════════════════════════
# Embed Colors
# ═══════════════════════════════════════════════════════════════════════════

COLOR_REGISTRATION = 0xF1C40F  # Gold
COLOR_WIN          = 0x2ECC71  # Green
COLOR_WIN_EPIC     = 0x00FF7F  # Spring green
COLOR_DEATH        = 0xE74C3C  # Red
COLOR_DEATH_EPIC   = 0x8B0000  # Dark red
COLOR_RUNE         = 0x9B59B6  # Purple
COLOR_ORB          = 0xE67E22  # Amber
COLOR_MILESTONE    = 0x3498DB  # Blue
COLOR_GHOST        = 0x8E44AD  # Deep purple
COLOR_UNIQUE       = 0xD4AC0D  # Dark gold
COLOR_GOD          = 0x1ABC9C  # Teal
COLOR_DIGEST       = 0x2C3E50  # Dark blue-grey
COLOR_BRANCH       = 0x27AE60  # Emerald
COLOR_ONLINE       = 0x3498DB  # Blue
COLOR_STATS        = 0x9B59B6  # Purple
COLOR_INFO         = 0x3498DB  # Blue
COLOR_RECORD       = 0xFFD700  # Gold
COLOR_ROLE         = 0x9966CC  # DCSS purple

# ═══════════════════════════════════════════════════════════════════════════
# DCSS Discord Roles — auto-assigned based on player stats
# ═══════════════════════════════════════════════════════════════════════════

DCSS_ROLE_DEFS = [
    # Entry — cool grey-blue
    {"key": "dcss_lost_soul",    "name": "Lost Soul",           "color": 0x8294B5, "emoji": "\U0001f47b",
     "flavor": "has entered the Dungeon for the first time — another soul lost to the depths.",
     "check": lambda s: s["gamesPlayed"] >= 1},
    {"key": "dcss_wanderer",     "name": "Wanderer",            "color": 0x7585C5, "emoji": "\U0001f9ed",
     "flavor": "reached XL 10 — the Dungeon hasn't claimed this one yet.",
     "check": lambda s: s["bestXL"] >= 10},

    # Progression — blue to indigo-purple
    {"key": "dcss_rune_seeker",  "name": "Rune Seeker",         "color": 0x7B75C8, "emoji": "\U0001f52e",
     "flavor": "obtained their first rune — the true quest begins!",
     "check": lambda s: s.get("maxRunes", 0) >= 1},
    {"key": "dcss_rune_bearer",  "name": "Rune Bearer",         "color": 0x8E65C0, "emoji": "\U0001f48E",
     "flavor": "obtained 3 runes — the gates of Zot beckon.",
     "check": lambda s: s.get("maxRunes", 0) >= 3},

    # Core Identity — purple to magenta
    {"key": "dcss_orb_victor",   "name": "Orb Victor",          "color": 0xA555B0, "emoji": "\U0001f3c6",
     "flavor": "escaped the Dungeon with the Orb of Zot!",
     "check": lambda s: s["wins"] >= 1},
    {"key": "dcss_orb_champion", "name": "Orb Champion",        "color": 0xB848A0, "emoji": "\U0001f396\ufe0f",
     "flavor": "escaped with the Orb 5 times — the Dungeon fears this one.",
     "check": lambda s: s["wins"] >= 5},
    {"key": "dcss_orb_ascendant","name": "Orb Ascendant",       "color": 0xC83D88, "emoji": "\u2694\ufe0f",
     "flavor": "escaped with the Orb 10 times — a legend of the depths.",
     "check": lambda s: s["wins"] >= 10},

    # Mastery — rose to red-orange
    {"key": "dcss_combo_hunter", "name": "Combo Hunter",        "color": 0xD53568, "emoji": "\U0001f3af",
     "flavor": "won with 5 unique combos — true versatility!",
     "check": lambda s: s.get("uniqueCombosWon", 0) >= 5},
    {"key": "dcss_combo_master", "name": "Combo Master",        "color": 0xDE3548, "emoji": "\U0001f9EC",
     "flavor": "won with 10 unique combos — master of all styles.",
     "check": lambda s: s.get("uniqueCombosWon", 0) >= 10},
    {"key": "dcss_acolyte",      "name": "Acolyte of the Pantheon", "color": 0xE25530, "emoji": "\U0001f54A\ufe0f",
     "flavor": "won under 3 different gods — the pantheon takes notice.",
     "check": lambda s: s.get("distinctGodsWon", 0) >= 3},
    {"key": "dcss_polytheist",   "name": "Polytheist",          "color": 0xE87D1C, "emoji": "\U0001f3DB\ufe0f",
     "flavor": "won under 10 different gods — blessed by the entire pantheon.",
     "check": lambda s: s.get("distinctGodsWon", 0) >= 10},

    # Elite — gold
    {"key": "dcss_15rune",       "name": "15-Rune Champion",    "color": 0xFFD700, "emoji": "\U0001f451",
     "flavor": "won with all 15 runes — the ultimate conquest!",
     "check": lambda s: s.get("has15RuneWin", False)},
]

# Role ordering: hardest at top
DCSS_ROLE_ORDER = [
    "dcss_15rune", "dcss_polytheist", "dcss_combo_master", "dcss_acolyte",
    "dcss_combo_hunter", "dcss_orb_ascendant", "dcss_orb_champion", "dcss_orb_victor",
    "dcss_rune_bearer", "dcss_rune_seeker", "dcss_wanderer", "dcss_lost_soul",
    "dcss_linked",
]

# Linked role — assigned on account verification (no stats check, no announcement)
LINKED_ROLE_DEF = {
    "key": "dcss_linked", "name": "Linked", "color": 0x99AAB5, "emoji": "\U0001f517",
}

# ── Discord Link Storage ─────────────────────────────────────────────────

def load_discord_links() -> dict:
    """Load discord_id → {username, verified, code} mappings."""
    try:
        with open(DISCORD_LINKS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_discord_links(links: dict) -> None:
    tmp = DISCORD_LINKS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(links, f, indent=2)
    os.replace(tmp, DISCORD_LINKS_FILE)


def load_role_state() -> dict:
    """Load role key → Discord role ID mappings."""
    try:
        with open(ROLE_STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_role_state(state: dict) -> None:
    tmp = ROLE_STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, ROLE_STATE_FILE)


def _fetch_player_stats_from(base_url: str, username: str) -> dict | None:
    """Fetch a single server's per-player scoring JSON. None if missing or unreachable."""
    url = f"{base_url}/scores/players/{urllib.request.quote(username.lower())}.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"{SERVER_NAME}-Bot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        log.warning(f"Failed to fetch stats from {base_url} for {username}: {e}")
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to fetch stats from {base_url} for {username}: {e}")
    return None


def fetch_player_stats(username: str) -> dict | None:
    """Fetch this server's per-player scoring JSON. Per-server linking — each bot
    trusts only its own userdb because the same username on different servers may
    belong to different people."""
    return _fetch_player_stats_from(SERVER_URL, username)


def username_exists(username: str) -> bool:
    """Check if a username exists in passwd.db3."""
    if not os.path.exists(PASSWD_DB):
        return False
    try:
        conn = sqlite3.connect(f"file:{PASSWD_DB}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT 1 FROM dglusers WHERE username = ? COLLATE NOCASE LIMIT 1",
            (username,),
        ).fetchone()
        conn.close()
        return row is not None
    except sqlite3.Error:
        return False


LINK_CODE_EXPIRY_SECONDS = 300  # 5 minutes


# ═══════════════════════════════════════════════════════════════════════════
# Flavor Text
# ═══════════════════════════════════════════════════════════════════════════

WIN_TITLES = [
    "escapes with the Orb of Zot!",
    "has conquered the Dungeon!",
    "emerges victorious!",
    "triumphs over the Dungeon!",
    "has beaten Crawl!",
    "achieves glory!",
    "returns with the Orb!",
    "survives the Dungeon!",
]

WIN_EPIC_TITLES = [
    "ASCENDS WITH ALL 15 RUNES!",
    "completes the ULTIMATE victory!",
    "the true champion emerges!",
    "has done the impossible \u2014 15 runes!",
    "leaves no rune behind!",
]

DEATH_FLAVOR = {
    "early": [
        "The dungeon is unforgiving.",
        "A brief adventure.",
        "Welcome to Crawl.",
        "Not everyone makes it past the entrance.",
        "The first steps are the hardest.",
        "Better luck next time.",
    ],
    "mid": [
        "Cut down in their prime.",
        "The dungeon claims another.",
        "A valiant effort.",
        "The adventure ends here.",
        "They fought well.",
        "Back to the drawing board.",
    ],
    "late": [
        "So close, yet so far.",
        "The dungeon's cruelest blow.",
        "An experienced adventurer falls.",
        "The deep dungeon is merciless.",
        "They delved too deep.",
    ],
    "max": [
        "Even the mightiest can fall.",
        "A maxed-out legend, gone.",
        "At the peak of power, yet...",
        "Not even full power was enough.",
    ],
    "with_runes": [
        "All those runes, for nothing.",
        "The runes weren't enough to save them.",
        "So many runes collected, but the dungeon wins.",
    ],
    "with_orb": [
        "THE ORB SLIPS AWAY!",
        "So close to escape!",
        "The cruelest death \u2014 with the Orb in hand.",
        "The Orb returns to the dungeon.",
        "Almost. ALMOST.",
    ],
}

DEATH_KILLER_SPECIAL = {
    "Sigmund": "Classic Sigmund.",
    "an adder": "Ssssurprise!",
    "a gnoll": "Gnolled it.",
    "a hobgoblin": "Not so humble after all.",
    "an orc priest": "Beogh sends his regards.",
    "Grinder": "Ground to dust.",
    "Prince Ribbit": "Ribbit, ribbit. You're dead.",
    "Menkaure": "Mummified.",
    "Ijyb": "The kobold strikes again.",
    "Terence": "Terence! Of all things!",
    "Jessica": "Jessica's still got it.",
    "Tiamat": "Dragon royalty is no joke.",
    "Cerebov": "The lord of fire prevails.",
    "the Royal Jelly": "Dissolved.",
    "Antaeus": "Frozen solid.",
    "Asmodeus": "The prince of hell collects another soul.",
    "Ereshkigal": "Dragged to the underworld.",
    "Dispater": "The Iron City claims another.",
    "Lom Lobon": "Outsmarted by a demon lord.",
    "Gloorx Vloq": "Darkness consumes all.",
    "Mnoleg": "Madness wins.",
    "Murray": "The mighty Murray!",
    "Dissolution": "Acid death.",
    "the Serpent of Hell": "Serpentine demise.",
    "Xtahua": "Dragon fire.",
}

DEATH_KTYP_FLAVOR = {
    "water": "Glub glub.",
    "lava": "Extra crispy.",
    "cloud": "Choked out.",
    "trap": "Watch your step!",
    "pois": "Poisoned.",
    "rot": "Rotted away.",
    "acid": "Dissolved.",
    "disintegration": "Atoms scattered.",
    "headbutt": "Bonk.",
}

NOTABLE_UNIQUES = {
    "Sigmund", "Grinder", "Ijyb", "Menkaure", "Duvessa", "Dowan",
    "Psyche", "Sonja", "Nessos", "Rupert", "Saint Roka", "Aizul",
    "Azrael", "Xtahua", "Vashnia", "Donald", "Louise", "Nikola",
    "Arachne", "Erica", "Erolcha", "Harold", "Josephine", "Joseph",
    "Maurice", "Norris", "Polyphemus", "Roxanne", "Snorg",
    "Fannar", "Gastronok", "Jorgrun", "Kirke", "Prince Ribbit",
    "Frederick", "Margery", "Mara", "Boris", "Murray",
    "Dissolution", "Lernaean hydra", "Serpent of Hell",
    "Antaeus", "Asmodeus", "Cerebov", "Dispater", "Ereshkigal",
    "Gloorx Vloq", "Lom Lobon", "Mnoleg", "the Royal Jelly",
    "Khufu", "Mennas", "Tiamat",
    "the Enchantress", "the Serpent of Hell",
}

NOTABLE_BRANCHES = {
    "Zot", "Slime", "Pan", "Tomb", "Abyss", "Depths", "Vaults",
    "Elf", "Crypt", "Coc", "Dis", "Geh", "Tar", "Zig", "Desolation",
    "Hell",
}

BORING_MILESTONES = {
    "begin", "start", "chargen", "identified", "spell", "monstrous",
    "sacrifice", "xom.effect", "buy", "hit", "learn",
}

NOTABLE_XL = {14, 18, 27}

RUNE_FLAVOR = {
    "golden": "The Tomb's treasure!",
    "silver": "Vaults breached!",
    "decaying": "From the Swamp's depths.",
    "serpentine": "The Snake Pit is cleared.",
    "slimy": "The Royal Jelly's prize!",
    "abyssal": "Escaped the Abyss with a prize!",
    "demonic": "A rune from Pandemonium!",
    "glowing": "A rune from Pandemonium!",
    "magical": "A rune from Pandemonium!",
    "dark": "A rune from Pandemonium!",
    "fiery": "From the Iron City of Dis!",
    "obsidian": "Gehenna's fiery prize!",
    "icy": "Cocytus frozen treasure!",
    "bone": "Tartarus relinquishes its rune!",
    "barnacled": "From the Shoals!",
    "gossamer": "Spider's Nest conquered!",
    "iron": "Forged in battle!",
}

# ═══════════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════════


def parse_xlog_line(line):
    """Parse a colon-delimited DCSS xlog line into a dict."""
    entry = {}
    parts = re.split(r":(?=[a-zA-Z_%]+=)", line.strip())
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            entry[k.strip()] = v.strip()
    return entry


def parse_timestamp(ts_str):
    """Parse DCSS timestamp to datetime object."""
    if not ts_str:
        return datetime.now(timezone.utc)
    clean = re.sub(r"[^0-9]", "", ts_str)[:14]
    try:
        return datetime.strptime(clean, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return datetime.now(timezone.utc)


def format_duration(seconds):
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return "?"
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def format_turns(turns):
    try:
        return f"{int(turns):,}"
    except (ValueError, TypeError):
        return "?"


def format_score(score):
    try:
        return f"{int(score):,}"
    except (ValueError, TypeError):
        return "0"


def capitalize_first(s):
    if not s:
        return s
    return s[0].upper() + s[1:]


def version_label(version):
    if version == "trunk":
        return "Trunk"
    return f"v{version}"


def is_win(entry):
    ktyp = entry.get("ktyp", "")
    if ktyp in ("winning", "winner"):
        return True
    tmsg = entry.get("tmsg", "").lower()
    return "escaped" in tmsg and "orb" in tmsg


def is_boring_death(entry):
    return entry.get("ktyp", "") in ("quitting", "leaving", "wizmode")


def combo_str(entry):
    return entry.get("char", "????")


def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def morgue_url(player):
    return f"{SERVER_URL}/morgue/{player}/"


# ═══════════════════════════════════════════════════════════════════════════
# State Management
# ═══════════════════════════════════════════════════════════════════════════


def new_daily_stats():
    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "games": 0,
        "wins": 0,
        "deaths": 0,
        "registrations": 0,
        "runes": 0,
        "players": [],
        "notable": [],
    }


def new_state():
    return {
        "version": STATE_VERSION,
        "file_offsets": {},
        "max_user_id": 0,
        "records": {
            "highest_score":    {"value": 0,         "player": "", "combo": "", "version": ""},
            "fastest_realtime": {"value": 999999999, "player": "", "combo": "", "version": ""},
            "fastest_turns":    {"value": 999999999, "player": "", "combo": "", "version": ""},
            "most_runes":       {"value": 0,         "player": "", "combo": "", "version": ""},
        },
        "combo_firsts": {},
        "player_stats": {},
        "top_scores": [],
        "total_games": 0,
        "total_wins": 0,
        "daily": new_daily_stats(),
        "last_digest": "",
        "initialized": False,
    }


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        if state.get("version") != STATE_VERSION:
            log.info("State version mismatch \u2014 starting fresh")
            return new_state()
        return state
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        log.info("No valid state file \u2014 starting fresh")
        return new_state()


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        log.error(f"Failed to save state: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Embed Builder
# ═══════════════════════════════════════════════════════════════════════════


def make_embed(title, description="", color=COLOR_MILESTONE, fields=None,
               footer=None, url=None, timestamp=None):
    """Build a discord.Embed with server defaults."""
    ts = timestamp if isinstance(timestamp, datetime) else datetime.now(timezone.utc)

    embed = discord.Embed(
        title=title,
        description=description or None,
        color=color,
        timestamp=ts,
        url=url,
    )
    if fields:
        for f in fields:
            embed.add_field(name=f["name"], value=f["value"], inline=f.get("inline", True))
    embed.set_footer(text=footer or f"{SERVER_NAME} \u2022 {SERVER_HOST}")
    return embed


# ═══════════════════════════════════════════════════════════════════════════
# Bot Class
# ═══════════════════════════════════════════════════════════════════════════


class WebTilesBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.state = load_state()
        self.notification_channel = None

    async def setup_hook(self):
        # Historical scan on first run (builds stats from existing logfiles)
        if not self.state.get("initialized"):
            self._historical_scan()

        # Register slash commands
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        log.info("Slash commands synced")

        # Start background tasks
        self.poll_games.start()
        self.poll_registrations.start()
        self.check_digest.start()
        self.update_presence.start()
        self.resync_roles.start()

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        if CHANNEL_ID:
            self.notification_channel = self.get_channel(CHANNEL_ID)
            if not self.notification_channel:
                try:
                    self.notification_channel = await self.fetch_channel(CHANNEL_ID)
                except discord.NotFound:
                    log.error(f"Notification channel {CHANNEL_ID} not found!")
                    return

            log.info("Bot ready — startup notification suppressed")

            # Ensure DCSS roles exist in guild and post/update guide (primary only)
            if GUILD_ID and IS_PRIMARY_BOT:
                guild = self.get_guild(GUILD_ID)
                if guild:
                    await self._ensure_dcss_roles(guild)
                    await self._post_roles_guide(guild)
        else:
            log.warning("DISCORD_CHANNEL_ID not set \u2014 notifications disabled")

    # ── DCSS Role Management ─────────────────────────────────────────────

    async def _ensure_dcss_roles(self, guild: discord.Guild) -> None:
        """Create/sync DCSS roles in the guild."""
        role_state = load_role_state()
        existing_roles = {r.id: r for r in guild.roles}
        created = 0

        for rdef in DCSS_ROLE_DEFS:
            # Check stored ID
            stored_id = role_state.get(rdef["key"])
            if stored_id:
                existing = existing_roles.get(int(stored_id))
                if existing:
                    if existing.name != rdef["name"] or existing.color.value != rdef["color"]:
                        try:
                            await existing.edit(name=rdef["name"], color=discord.Color(rdef["color"]), reason=f"{SERVER_NAME} role sync")
                            log.info(f"[roles] Updated: {existing.name} → {rdef['name']}")
                        except discord.HTTPException as e:
                            log.error(f"[roles] Failed to update {rdef['name']}: {e}")
                    continue

            # Find by name
            by_name = discord.utils.get(existing_roles.values(), name=rdef["name"])
            if by_name:
                role_state[rdef["key"]] = str(by_name.id)
                continue

            # Create
            try:
                role = await guild.create_role(
                    name=rdef["name"], color=discord.Color(rdef["color"]),
                    mentionable=False, reason=f"{SERVER_NAME} DCSS auto-role",
                )
                role_state[rdef["key"]] = str(role.id)
                created += 1
                log.info(f"[roles] Created: {rdef['name']} ({role.id})")
            except discord.HTTPException as e:
                log.error(f"[roles] Failed to create {rdef['name']}: {e}")

        # Ensure Linked role exists
        lkey = LINKED_ROLE_DEF["key"]
        stored_id = role_state.get(lkey)
        if stored_id:
            existing = existing_roles.get(int(stored_id))
            if existing:
                if existing.name != LINKED_ROLE_DEF["name"] or existing.color.value != LINKED_ROLE_DEF["color"]:
                    try:
                        await existing.edit(name=LINKED_ROLE_DEF["name"], color=discord.Color(LINKED_ROLE_DEF["color"]), reason=f"{SERVER_NAME} role sync")
                    except discord.HTTPException:
                        pass
            else:
                role_state.pop(lkey, None)
                stored_id = None
        if not stored_id:
            by_name = discord.utils.get(existing_roles.values(), name=LINKED_ROLE_DEF["name"])
            if by_name:
                role_state[lkey] = str(by_name.id)
            else:
                try:
                    role = await guild.create_role(
                        name=LINKED_ROLE_DEF["name"], color=discord.Color(LINKED_ROLE_DEF["color"]),
                        mentionable=False, reason=f"{SERVER_NAME} Linked role",
                    )
                    role_state[lkey] = str(role.id)
                    created += 1
                    log.info(f"[roles] Created: {LINKED_ROLE_DEF['name']} ({role.id})")
                except discord.HTTPException as e:
                    log.error(f"[roles] Failed to create Linked role: {e}")

        # Remove old roles no longer in DCSS_ROLE_DEFS
        current_keys = {rdef["key"] for rdef in DCSS_ROLE_DEFS} | {LINKED_ROLE_DEF["key"]}
        stale_keys = [k for k in list(role_state) if k.startswith("dcss_") and k not in current_keys and k != "_guide_message_id"]
        for key in stale_keys:
            old_id = role_state.pop(key, None)
            if old_id:
                old_role = existing_roles.get(int(old_id))
                if old_role:
                    try:
                        await old_role.delete(reason=f"{SERVER_NAME} role cleanup — role removed from system")
                        log.info(f"[roles] Deleted old role: {old_role.name} ({old_id})")
                    except discord.HTTPException as e:
                        log.error(f"[roles] Failed to delete old role {key}: {e}")

        save_role_state(role_state)
        if created:
            log.info(f"[roles] Created {created} new DCSS roles")
        else:
            log.info(f"[roles] All {len(DCSS_ROLE_DEFS)} DCSS roles up to date")
        if stale_keys:
            log.info(f"[roles] Cleaned up {len(stale_keys)} old roles: {', '.join(stale_keys)}")

        # Order roles by difficulty — hardest at top, easiest at bottom (position 1)
        try:
            role_objects = []
            for key in DCSS_ROLE_ORDER:
                rid = role_state.get(key)
                if rid:
                    role_obj = guild.get_role(int(rid))
                    if role_obj:
                        role_objects.append(role_obj)
            if role_objects:
                # Assign positions: first in DCSS_ROLE_ORDER (hardest) gets highest position
                positions = {}
                for i, role_obj in enumerate(role_objects):
                    positions[role_obj] = len(role_objects) - i
                await guild.edit_role_positions(positions=positions)
                log.info(f"[roles] Ordered {len(positions)} roles by difficulty")
        except discord.HTTPException as e:
            log.error(f"[roles] Failed to order roles: {e}")

    async def _post_roles_guide(self, guild: discord.Guild) -> None:
        """Post or update the DCSS roles guide in the designated channel."""
        if not ROLE_GUIDE_CHANNEL:
            return
        role_state = load_role_state()

        def mention(key):
            rid = role_state.get(key)
            return f"<@&{rid}>" if rid else "???"

        requirements = {
            "dcss_lost_soul": "Play 1 game",
            "dcss_wanderer": "Reach XL 10",
            "dcss_rune_seeker": "Obtain 1 rune",
            "dcss_rune_bearer": "Obtain 3 runes",
            "dcss_orb_victor": "Win a game",
            "dcss_orb_champion": "Win 5 games",
            "dcss_orb_ascendant": "Win 10 games",
            "dcss_combo_hunter": "Win with 5 unique combos",
            "dcss_combo_master": "Win with 10 unique combos",
            "dcss_acolyte": "Win with 3 different gods",
            "dcss_polytheist": "Win with 10 different gods",
            "dcss_15rune": "Win with all 15 runes",
        }

        # Show every server's commands so players know which one to use for which account
        link_cmds = [f"`/link-{SERVER_SLUG}`"]
        verify_cmds = [f"`/verify-{SERVER_SLUG}`"]
        if OTHER_SERVER_SLUG:
            link_cmds.append(f"`/link-{OTHER_SERVER_SLUG}`")
            verify_cmds.append(f"`/verify-{OTHER_SERVER_SLUG}`")

        embed1 = discord.Embed(
            title="\U0001f3f0 DCSS Auto-Roles",
            color=COLOR_ROLE,
            description=(
                "Link your DCSS account to earn Discord roles based on your achievements!\n\n"
                "**How to link:**\n"
                f"1. Run {' or '.join(link_cmds)} `<username>` (one per server you play on)\n"
                "2. Add the verification code to any RC file on that server (any version works)\n"
                f"3. Run {' or '.join(verify_cmds)} within 5 minutes\n"
                "4. Roles are assigned instantly!\n\n"
                "Roles update live when your game ends, and resync every 15 minutes. "
                "Achievements from any linked server count — link both if you play both."
            ),
        )

        lines = [f"{LINKED_ROLE_DEF['emoji']} {mention(LINKED_ROLE_DEF['key'])} — Connect your account"]
        for rdef in DCSS_ROLE_DEFS:
            req = requirements.get(rdef["key"], "")
            lines.append(f"{rdef['emoji']} {mention(rdef['key'])} — {req}")

        embed2 = discord.Embed(
            title="DCSS",
            color=COLOR_ROLE,
            description="\n".join(lines),
        )
        # Footer omitted \u2014 guide is server-agnostic so it stays seamless across both bots

        embeds = [embed1, embed2]

        try:
            channel = self.get_channel(int(ROLE_GUIDE_CHANNEL))
            if not channel:
                channel = await self.fetch_channel(int(ROLE_GUIDE_CHANNEL))
            if not channel:
                log.error("[roles] Guide channel not found")
                return

            # Check for existing guide message ID in role state
            existing_id = role_state.get("_guide_message_id")
            if existing_id:
                try:
                    msg = await channel.fetch_message(int(existing_id))
                    await msg.edit(embeds=embeds)
                    log.info("[roles] Updated DCSS roles guide")
                    return
                except (discord.NotFound, discord.HTTPException):
                    pass

            sent = await channel.send(embeds=embeds)
            role_state["_guide_message_id"] = str(sent.id)
            save_role_state(role_state)
            log.info(f"[roles] Posted DCSS roles guide (message ID: {sent.id})")
        except Exception as e:
            log.error(f"[roles] Failed to post guide: {e}")

    async def sync_member_roles(self, member: discord.Member, stats: dict) -> list[str]:
        """Sync DCSS roles for a member based on their stats. Returns list of newly added role names."""
        role_state = load_role_state()
        added = []

        # Ensure Linked role is assigned (no announcement)
        linked_id = role_state.get(LINKED_ROLE_DEF["key"])
        if linked_id and not member.get_role(int(linked_id)):
            try:
                await member.add_roles(discord.Object(id=int(linked_id)), reason=f"{SERVER_NAME} account linked")
            except discord.HTTPException as e:
                log.error(f"[roles] Failed to add Linked role to {member}: {e}")

        for rdef in DCSS_ROLE_DEFS:
            role_id = role_state.get(rdef["key"])
            if not role_id:
                continue

            has_role = member.get_role(int(role_id)) is not None
            qualifies = rdef["check"](stats)

            # Add-only: removing roles based on stats would clobber roles granted by the other server's bot.
            if qualifies and not has_role:
                try:
                    await member.add_roles(discord.Object(id=int(role_id)), reason=f"{SERVER_NAME} DCSS stats sync")
                    added.append(rdef)
                except discord.HTTPException as e:
                    log.error(f"[roles] Failed to add {rdef['name']} to {member}: {e}")

        if added:
            log.info(f"[roles] {member}: +[{', '.join(r['name'] for r in added)}]")

        # Announce new roles
        announce_channel_id = ROLE_ANNOUNCE_CHANNEL
        if added and announce_channel_id:
            for rdef in added:
                try:
                    channel = self.get_channel(int(announce_channel_id))
                    if not channel:
                        channel = await self.fetch_channel(int(announce_channel_id))
                    if channel:
                        role_id = role_state.get(rdef["key"])
                        embed = discord.Embed(
                            color=rdef["color"],
                            description=(
                                f"{rdef['emoji']} <@{member.id}> {rdef['flavor']}\n\n"
                                f"Earned the <@&{role_id}> role!"
                            ),
                            timestamp=datetime.now(timezone.utc),
                        )
                        embed.set_footer(text=SERVER_HOST)
                        await channel.send(embed=embed)
                except Exception as e:
                    log.error(f"[roles] Failed to announce: {e}")

        return [r["name"] for r in added]

    @tasks.loop(minutes=15)
    async def resync_roles(self):
        """Periodically resync roles for all linked players."""
        if not GUILD_ID:
            return
        guild = self.get_guild(GUILD_ID)
        if not guild:
            return

        links = load_discord_links()
        verified = {did: info for did, info in links.items() if info.get("verified")}
        if not verified:
            return

        synced = 0
        for discord_id, info in verified.items():
            username = info["username"]
            stats = fetch_player_stats(username)
            if not stats:
                continue
            try:
                member = guild.get_member(int(discord_id))
                if not member:
                    member = await guild.fetch_member(int(discord_id))
                if member:
                    await self.sync_member_roles(member, stats)
                    synced += 1
            except (discord.NotFound, discord.HTTPException):
                continue

        if synced:
            log.info(f"[roles] Periodic resync: {synced}/{len(verified)} members updated")

    async def _sync_roles_for_player(self, username: str) -> None:
        """Sync roles for a linked player by server username (called after game events)."""
        if not GUILD_ID:
            return
        links = load_discord_links()
        # Find discord_id for this username
        discord_id = None
        for did, info in links.items():
            if info.get("verified") and info.get("username", "").lower() == username.lower():
                discord_id = did
                break
        if not discord_id:
            return

        guild = self.get_guild(GUILD_ID)
        if not guild:
            return

        stats = fetch_player_stats(username)
        if not stats:
            return

        try:
            member = guild.get_member(int(discord_id))
            if not member:
                member = await guild.fetch_member(int(discord_id))
            if member:
                await self.sync_member_roles(member, stats)
        except (discord.NotFound, discord.HTTPException):
            pass

    @resync_roles.before_loop
    async def before_resync_roles(self):
        await self.wait_until_ready()

    async def send_embed(self, embed):
        """Send an embed to the notification channel."""
        if not self.notification_channel:
            return
        try:
            await self.notification_channel.send(embed=embed)
        except discord.HTTPException as e:
            log.error(f"Failed to send embed: {e}")

    # ── Historical Scan ──────────────────────────────────────────────────

    def _historical_scan(self):
        """Parse all existing logfiles on startup to build complete stats."""
        log.info("Historical scan of all logfiles...")
        total = 0

        for data_dir, version in VERSION_DIRS:
            logfile = os.path.join(data_dir, "logfile")
            if not os.path.exists(logfile):
                continue
            with open(logfile, "r", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = parse_xlog_line(line)
                    if entry.get("name"):
                        self._update_stats(entry, version)
                        total += 1
            self.state["file_offsets"][logfile] = os.path.getsize(logfile)

        # Set milestone offsets to end (skip existing, don't replay)
        for data_dir, version in VERSION_DIRS:
            ms = os.path.join(data_dir, "milestones")
            if os.path.exists(ms):
                self.state["file_offsets"][ms] = os.path.getsize(ms)

        # Initialize registration tracking
        self._init_registrations()

        self.state["initialized"] = True
        save_state(self.state)
        log.info(
            f"Scan complete: {total} games, {self.state['total_wins']} wins, "
            f"{len(self.state['combo_firsts'])} winning combos"
        )

    def _init_registrations(self):
        """Set max_user_id to current max without notifying."""
        if not os.path.exists(PASSWD_DB):
            return
        try:
            conn = sqlite3.connect(f"file:{PASSWD_DB}?mode=ro", uri=True)
            row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM dglusers").fetchone()
            self.state["max_user_id"] = row[0] or 0
            conn.close()
            log.info(f"Registration tracking initialized (max ID: {self.state['max_user_id']})")
        except sqlite3.Error as e:
            log.warning(f"Cannot read passwd.db3: {e}")

    # ── Stats Update (shared between scan and live) ──────────────────────

    def _update_stats(self, entry, version):
        """Update player stats, records, top scores from a logfile entry.
        Returns achievement info dict for use by notification handlers."""
        name = entry.get("name", "")
        score = safe_int(entry.get("sc", 0))
        combo = combo_str(entry)
        win = is_win(entry)

        ps = self.state["player_stats"].setdefault(name, {
            "games": 0, "wins": 0, "best_score": 0, "best_combo": "",
            "streak": 0, "best_streak": 0, "last_was_win": False,
        })
        ps["games"] += 1
        self.state["total_games"] += 1

        personal_best = score > ps["best_score"]
        if personal_best:
            ps["best_score"] = score
            ps["best_combo"] = combo

        result = {"personal_best": personal_best}

        if win:
            ps["wins"] += 1
            self.state["total_wins"] += 1

            if ps["last_was_win"]:
                ps["streak"] += 1
            else:
                ps["streak"] = 1
            ps["last_was_win"] = True
            if ps["streak"] > ps["best_streak"]:
                ps["best_streak"] = ps["streak"]

            result["win_number"] = ps["wins"]
            result["streak"] = ps["streak"]

            # Records
            records_broken = []
            recs = self.state["records"]
            runes = safe_int(entry.get("urune", entry.get("runes", 0)))
            dur = safe_int(entry.get("dur", 0))
            turns = safe_int(entry.get("turn", 0))

            if score > recs["highest_score"]["value"]:
                old = recs["highest_score"]["value"]
                recs["highest_score"] = {
                    "value": score, "player": name, "combo": combo, "version": version,
                }
                if old > 0:
                    records_broken.append(f"New highest score! (was {format_score(old)})")

            if dur > 0 and dur < recs["fastest_realtime"]["value"]:
                old_dur = recs["fastest_realtime"]["value"]
                recs["fastest_realtime"] = {
                    "value": dur, "player": name, "combo": combo, "version": version,
                }
                if old_dur < 999999999:
                    records_broken.append(f"Fastest win! (was {format_duration(old_dur)})")

            if turns > 0 and turns < recs["fastest_turns"]["value"]:
                old_turns = recs["fastest_turns"]["value"]
                recs["fastest_turns"] = {
                    "value": turns, "player": name, "combo": combo, "version": version,
                }
                if old_turns < 999999999:
                    records_broken.append(f"Fewest turns! (was {format_turns(old_turns)})")

            if runes > recs["most_runes"]["value"]:
                recs["most_runes"] = {
                    "value": runes, "player": name, "combo": combo, "version": version,
                }

            result["records_broken"] = records_broken

            # Combo firsts
            combo_first = combo not in self.state["combo_firsts"]
            if combo_first:
                self.state["combo_firsts"][combo] = name
            result["combo_first"] = combo_first

            # Top scores (keep top 20)
            self.state["top_scores"].append({
                "player": name, "combo": combo, "score": score,
                "runes": runes, "version": version,
            })
            self.state["top_scores"].sort(key=lambda x: x["score"], reverse=True)
            self.state["top_scores"] = self.state["top_scores"][:20]
        else:
            broken_streak = ps.get("streak", 0) if ps.get("last_was_win") else 0
            ps["last_was_win"] = False
            ps["streak"] = 0
            result["broken_streak"] = broken_streak

        return result

    # ── Background Tasks ─────────────────────────────────────────────────

    @tasks.loop(seconds=POLL_INTERVAL)
    async def poll_games(self):
        for data_dir, version in VERSION_DIRS:
            for file_type in WATCH_FILES:
                filepath = os.path.join(data_dir, file_type)
                await self._process_file(filepath, version, file_type)

        # Save state every ~60s
        if self.poll_games.current_loop % 12 == 0:
            save_state(self.state)

    @poll_games.before_loop
    async def before_poll_games(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=REG_POLL_INTERVAL)
    async def poll_registrations(self):
        await self._check_registrations()

    @poll_registrations.before_loop
    async def before_poll_registrations(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=1)
    async def check_digest(self):
        await self._maybe_post_digest()

    @check_digest.before_loop
    async def before_check_digest(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=2)
    async def update_presence(self):
        daily = self.state.get("daily", {})
        games = daily.get("games", 0)
        wins = daily.get("wins", 0)
        status = f"{games} games today ({wins} wins)"
        await self.change_presence(activity=discord.Game(name=status))

    @update_presence.before_loop
    async def before_update_presence(self):
        await self.wait_until_ready()

    # ── File Processing ──────────────────────────────────────────────────

    async def _process_file(self, filepath, version, file_type):
        if not os.path.exists(filepath):
            return

        offset = self.state["file_offsets"].get(filepath)
        try:
            file_size = os.path.getsize(filepath)
        except OSError:
            return

        if offset is None:
            # New file appeared after initialization
            self.state["file_offsets"][filepath] = file_size
            return

        if offset > file_size:
            log.info(f"File truncated: {filepath}")
            offset = 0

        if offset >= file_size:
            return

        try:
            with open(filepath, "r", errors="replace") as f:
                f.seek(offset)
                new_data = f.read()
                new_offset = f.tell()
        except OSError as e:
            log.error(f"Error reading {filepath}: {e}")
            return

        self.state["file_offsets"][filepath] = new_offset

        for line in new_data.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            entry = parse_xlog_line(line)
            if not entry.get("name"):
                continue

            try:
                if file_type == "logfile":
                    result = self._update_stats(entry, version)
                    self.state["daily"]["games"] += 1
                    name = entry.get("name", "Unknown")
                    if name not in self.state["daily"]["players"]:
                        self.state["daily"]["players"].append(name)

                    if is_win(entry):
                        await self._notify_win(entry, version, result)
                    elif not is_boring_death(entry):
                        await self._notify_death(entry, version, result)

                    # Live role sync after each game — both bots manage their own linked users
                    await self._sync_roles_for_player(name)

                elif file_type == "milestones":
                    await self._handle_milestone(entry, version)
            except Exception as e:
                log.error(f"Error processing entry: {e}", exc_info=True)

    # ── Registration Watcher ─────────────────────────────────────────────

    async def _check_registrations(self):
        if not os.path.exists(PASSWD_DB):
            return
        try:
            conn = sqlite3.connect(f"file:{PASSWD_DB}?mode=ro", uri=True)
            conn.execute("PRAGMA query_only=ON")
        except sqlite3.Error as e:
            log.warning(f"Cannot open passwd.db3: {e}")
            return

        try:
            row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM dglusers").fetchone()
            current_max = row[0] or 0
            prev_max = self.state.get("max_user_id", 0)

            if current_max > prev_max:
                cursor = conn.execute(
                    "SELECT id, username FROM dglusers WHERE id > ? ORDER BY id",
                    (prev_max,),
                )
                for user_id, username in cursor.fetchall():
                    log.info(f"New registration: {username} (ID: {user_id})")
                    embed = make_embed(
                        title=f"\U0001f44b Welcome, {username}!",
                        description=(
                            f"A new adventurer has joined **{SERVER_NAME}**!\n\n"
                            f"Good luck in the Dungeon!"
                        ),
                        color=COLOR_REGISTRATION,
                        fields=[
                            {"name": "Play Now", "value": f"[WebTiles]({SERVER_URL})", "inline": True},
                            {"name": "SSH", "value": f"`ssh -p 222 crawl@{SERVER_HOST}`", "inline": True},
                        ],
                    )
                    await self.send_embed(embed)
                    self.state["daily"]["registrations"] += 1

                self.state["max_user_id"] = current_max
        except sqlite3.Error as e:
            log.warning(f"Error querying passwd.db3: {e}")
        finally:
            conn.close()

    # ── Win Notification ─────────────────────────────────────────────────

    async def _notify_win(self, entry, version, result):
        name   = entry.get("name", "Unknown")
        race   = entry.get("race", "?")
        cls    = entry.get("cls", entry.get("bg", "?"))
        combo  = combo_str(entry)
        god    = entry.get("god", "")
        score  = safe_int(entry.get("sc", 0))
        runes  = safe_int(entry.get("urune", entry.get("runes", 0)))
        dur    = safe_int(entry.get("dur", 0))
        turns  = safe_int(entry.get("turn", 0))
        xl     = safe_int(entry.get("xl", 0))

        win_number     = result.get("win_number", 1)
        streak         = result.get("streak", 1)
        combo_first    = result.get("combo_first", False)
        personal_best  = result.get("personal_best", False)
        records_broken = result.get("records_broken", [])

        is_epic = runes >= 15 or records_broken or combo_first
        if is_epic:
            title_text = random.choice(WIN_EPIC_TITLES) if runes >= 15 else random.choice(WIN_TITLES)
            color = COLOR_WIN_EPIC
        else:
            title_text = random.choice(WIN_TITLES)
            color = COLOR_WIN

        god_text = f" of {god}" if god else ""
        desc_parts = [f"**{race} {cls}{god_text}** ({combo})"]

        if combo_first:
            desc_parts.append(f"\u2b50 **First ever {combo} win on {SERVER_NAME}!**")
        if win_number == 1:
            desc_parts.append(f"\U0001f389 **First win for {name}!**")
        else:
            desc_parts.append(f"Win #{win_number} for {name}")
        if streak >= 3:
            desc_parts.append(f"\U0001f525 **{streak}-game winning streak!**")
        elif streak == 2:
            desc_parts.append("Streak: 2 wins in a row!")
        if personal_best and win_number > 1:
            desc_parts.append("\U0001f4c8 New personal best score!")
        for rec in records_broken:
            desc_parts.append(f"\U0001f3c5 **{rec}**")

        embed = make_embed(
            title=f"\U0001f3c6 {name} {title_text}",
            description="\n".join(desc_parts),
            color=color,
            fields=[
                {"name": "Score",    "value": format_score(score), "inline": True},
                {"name": "Runes",    "value": str(runes),          "inline": True},
                {"name": "XL",       "value": str(xl),             "inline": True},
                {"name": "Duration", "value": format_duration(dur), "inline": True},
                {"name": "Turns",    "value": format_turns(turns),  "inline": True},
                {"name": "Version",  "value": version_label(version), "inline": True},
            ],
            url=morgue_url(name),
            timestamp=parse_timestamp(entry.get("end", "")),
        )
        await self.send_embed(embed)

        # Daily tracking
        self.state["daily"]["wins"] += 1
        event = f"\U0001f3c6 {name} ({combo}) won with {runes} runes"
        if records_broken:
            event += " \u2014 " + ", ".join(records_broken)
        self.state["daily"]["notable"].append(event)
        log.info(f"WIN: {name} ({combo}) \u2014 {runes} runes, {format_score(score)} pts")

    # ── Death Notification ───────────────────────────────────────────────

    async def _notify_death(self, entry, version, result):
        name   = entry.get("name", "Unknown")
        race   = entry.get("race", "?")
        cls    = entry.get("cls", entry.get("bg", "?"))
        combo  = combo_str(entry)
        xl     = safe_int(entry.get("xl", 0))
        place  = entry.get("place", "???").replace("::", ":")
        killer = entry.get("killer", "something")
        ktyp   = entry.get("ktyp", "")
        tmsg   = entry.get("tmsg", "died")
        score  = safe_int(entry.get("sc", 0))
        runes  = safe_int(entry.get("urune", entry.get("runes", 0)))
        turns  = safe_int(entry.get("turn", 0))
        god    = entry.get("god", "")
        dur    = safe_int(entry.get("dur", 0))

        if xl < DEATH_MIN_XL:
            return

        broken_streak = result.get("broken_streak", 0)
        has_orb = "orb" in tmsg.lower()
        is_notable = xl >= 15 or runes > 0 or has_orb

        # Pick flavor text
        if has_orb:
            flavor = random.choice(DEATH_FLAVOR["with_orb"])
        elif runes > 0:
            flavor = random.choice(DEATH_FLAVOR["with_runes"])
        elif killer in DEATH_KILLER_SPECIAL:
            flavor = DEATH_KILLER_SPECIAL[killer]
        elif ktyp in DEATH_KTYP_FLAVOR:
            flavor = DEATH_KTYP_FLAVOR[ktyp]
        elif xl >= 27:
            flavor = random.choice(DEATH_FLAVOR["max"])
        elif xl >= 15:
            flavor = random.choice(DEATH_FLAVOR["late"])
        elif xl >= 6:
            flavor = random.choice(DEATH_FLAVOR["mid"])
        else:
            flavor = random.choice(DEATH_FLAVOR["early"])

        god_text = f" of {god}" if god else ""

        if has_orb:
            title = f"\U0001f480 {name} DIES WITH THE ORB!"
            description = (
                f"**{race} {cls}{god_text}** ({combo})\n"
                f"{capitalize_first(tmsg)}\n\n*{flavor}*"
            )
            if broken_streak >= 3:
                description += f"\n\n\U0001f622 **{broken_streak}-game winning streak broken!**"
            fields = [
                {"name": "Place",    "value": place,               "inline": True},
                {"name": "Killer",   "value": killer,              "inline": True},
                {"name": "XL",       "value": str(xl),             "inline": True},
                {"name": "Score",    "value": format_score(score), "inline": True},
                {"name": "Runes",    "value": str(runes),          "inline": True},
                {"name": "Duration", "value": format_duration(dur), "inline": True},
            ]
            embed = make_embed(
                title=title, description=description, color=COLOR_DEATH_EPIC,
                fields=fields, url=morgue_url(name),
                timestamp=parse_timestamp(entry.get("end", "")),
            )

        elif is_notable:
            title = f"\U0001f480 {name} the {combo} has perished"
            description = (
                f"**{race} {cls}{god_text}**\n"
                f"{capitalize_first(tmsg)}\n\n*{flavor}*"
            )
            if broken_streak >= 3:
                description += f"\n\n\U0001f622 **{broken_streak}-game winning streak broken!**"
            fields = [
                {"name": "Place", "value": place, "inline": True},
                {"name": "XL",    "value": str(xl), "inline": True},
            ]
            if runes > 0:
                fields.append({"name": "Runes", "value": str(runes), "inline": True})
            fields.extend([
                {"name": "Score",   "value": format_score(score),    "inline": True},
                {"name": "Turns",   "value": format_turns(turns),    "inline": True},
                {"name": "Version", "value": version_label(version), "inline": True},
            ])
            embed = make_embed(
                title=title, description=description, color=COLOR_DEATH,
                fields=fields, url=morgue_url(name),
                timestamp=parse_timestamp(entry.get("end", "")),
            )

        else:
            title = f"\U0001f480 {name} the {race} {cls}{god_text}"
            description = f"{capitalize_first(tmsg)} (XL {xl}, {place})"
            if flavor:
                description += f"\n*{flavor}*"
            if broken_streak >= 3:
                description += f"\n\U0001f622 **{broken_streak}-game winning streak broken!**"
            embed = make_embed(
                title=title, description=description, color=COLOR_DEATH,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
                timestamp=parse_timestamp(entry.get("end", "")),
            )

        await self.send_embed(embed)

        self.state["daily"]["deaths"] += 1
        if has_orb:
            self.state["daily"]["notable"].append(
                f"\U0001f480 {name} ({combo}) died WITH THE ORB at {place}!"
            )
        log.info(f"DEATH: {name} ({combo}) XL{xl} at {place} \u2014 {killer}")

    # ── Milestone Handler ────────────────────────────────────────────────

    async def _handle_milestone(self, entry, version):
        mtype         = entry.get("type", "")
        name          = entry.get("name", "Unknown")
        race          = entry.get("race", "?")
        cls           = entry.get("cls", entry.get("bg", "?"))
        combo         = combo_str(entry)
        xl            = safe_int(entry.get("xl", 0))
        place         = entry.get("place", "???").replace("::", ":")
        milestone_msg = entry.get("milestone", "")
        god           = entry.get("god", "")

        if mtype in BORING_MILESTONES:
            return

        # XL milestones
        if mtype in ("xl", "char"):
            if xl not in NOTABLE_XL:
                return
            xl_desc = {14: "mid-game", 18: "late-game", 27: "MAX LEVEL"}
            embed = make_embed(
                title=f"\u2b06\ufe0f {name} reached XL {xl}!",
                description=f"**{race} {cls}** ({combo}) \u2014 {xl_desc.get(xl, '')}",
                color=COLOR_MILESTONE,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)
            return

        # Rune
        if mtype == "rune":
            rune_match = re.search(
                r"found (?:an? )?(.+?)(?:\s*rune| rune)", milestone_msg, re.IGNORECASE
            )
            rune_name = rune_match.group(1).strip() if rune_match else ""
            rune_flavor = RUNE_FLAVOR.get(rune_name, "")
            rune_count = re.search(r"\((\d+/\d+)\)", milestone_msg)
            count_str = f" ({rune_count.group(1)})" if rune_count else ""

            desc = f"**{race} {cls}** ({combo}) at {place}, XL {xl}"
            if rune_flavor:
                desc += f"\n*{rune_flavor}*"

            embed = make_embed(
                title=f"\U0001f538 {name} found the {rune_name}rune!{count_str}",
                description=desc,
                color=COLOR_RUNE,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)
            self.state["daily"]["runes"] += 1
            return

        # Orb of Zot
        if mtype == "orb":
            embed = make_embed(
                title=f"\U0001f31f {name} has the Orb of Zot!",
                description=(
                    f"**{race} {cls}** ({combo}) \u2014 XL {xl}\n"
                    f"Now they just need to get out alive..."
                ),
                color=COLOR_ORB,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)
            self.state["daily"]["notable"].append(
                f"\U0001f31f {name} ({combo}) picked up the Orb!"
            )
            return

        # Ghost kill
        if mtype in ("ghost.kill", "ghost"):
            ghost_match = re.search(r"ghost of (\S+)", milestone_msg)
            ghost_name = ghost_match.group(1) if ghost_match else "a ghost"
            embed = make_embed(
                title=f"\U0001f47b {name} defeated a ghost!",
                description=(
                    f"**{race} {cls}** ({combo}) defeated the ghost of "
                    f"**{ghost_name}** at {place}"
                ),
                color=COLOR_GHOST,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)
            return

        # Unique kills
        if mtype in ("uniq", "uniq.ban"):
            uniq_match = re.search(r"killed (.+?)\.?\s*$", milestone_msg)
            uniq_name = uniq_match.group(1).strip() if uniq_match else ""
            if uniq_name not in NOTABLE_UNIQUES:
                if not any(u in milestone_msg for u in NOTABLE_UNIQUES):
                    return
            embed = make_embed(
                title=f"\u2694\ufe0f {name} slew {uniq_name}!",
                description=f"**{race} {cls}** ({combo}) at {place}, XL {xl}",
                color=COLOR_UNIQUE,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)
            return

        # Branch entry/completion
        if mtype in ("br.enter", "br.end", "br.final", "br.mid", "enter"):
            branch = place.split(":")[0]
            if branch not in NOTABLE_BRANCHES:
                return

            if mtype in ("br.enter", "enter"):
                emoji, action = "\U0001f6aa", f"entered {branch}"
            elif mtype == "br.final":
                emoji, action = "\U0001f3c1", f"reached the bottom of {branch}"
            elif mtype == "br.end":
                emoji, action = "\U0001f4cd", f"reached the end of {branch}"
            else:
                return

            embed = make_embed(
                title=f"{emoji} {name} {action}!",
                description=f"**{race} {cls}** ({combo}) \u2014 XL {xl}",
                color=COLOR_BRANCH,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)
            return

        # God events
        if mtype in ("god.worship", "god.join"):
            if not god:
                return
            embed = make_embed(
                title=f"\u26ea {name} worships {god}!",
                description=f"**{race} {cls}** ({combo}) at {place}",
                color=COLOR_GOD,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)
            return

        if mtype == "god.renounce":
            old_god = re.search(r"abandoned (.+?)$", milestone_msg)
            god_name = old_god.group(1).strip().rstrip(".") if old_god else "their god"
            embed = make_embed(
                title=f"\u26a1 {name} abandoned {god_name}!",
                description=f"**{race} {cls}** ({combo}) \u2014 Bold move.",
                color=COLOR_GOD,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)
            return

        if mtype == "god.maxpiety":
            if not god:
                return
            embed = make_embed(
                title=f"\u2728 {name} reached max piety with {god}!",
                description=f"**{race} {cls}** ({combo}) \u2014 XL {xl}",
                color=COLOR_GOD,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)
            return

        # Shaft
        if mtype == "shaft":
            embed = make_embed(
                title=f"\U0001f573\ufe0f {name} fell down a shaft!",
                description=f"**{race} {cls}** ({combo}) at {place} \u2014 Wheee!",
                color=COLOR_MILESTONE,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)
            return

        # Abyss escape
        if mtype == "abyss.exit":
            embed = make_embed(
                title=f"\U0001f300 {name} escaped the Abyss!",
                description=f"**{race} {cls}** ({combo}) \u2014 XL {xl}. Back to reality.",
                color=COLOR_BRANCH,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)
            return

        # Ziggurat
        if mtype == "zig":
            zig_match = re.search(r"(\d+)", milestone_msg)
            floor = safe_int(zig_match.group(1)) if zig_match else 0
            if floor >= 10:
                desc = "Insanity!" if floor >= 20 else "Deep in the Ziggurat."
                embed = make_embed(
                    title=f"\U0001f5fc {name} reached Zig:{floor}!",
                    description=f"**{race} {cls}** ({combo}) \u2014 {desc}",
                    color=COLOR_BRANCH,
                    footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
                )
                await self.send_embed(embed)
            return

        # Escape via milestone (usually caught in logfile, but just in case)
        if "escape" in milestone_msg.lower() or "won" in milestone_msg.lower():
            embed = make_embed(
                title=f"\U0001f31f {name} ({combo})",
                description=capitalize_first(milestone_msg),
                color=COLOR_WIN,
                footer=f"{version_label(version)} \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}",
            )
            await self.send_embed(embed)

    # ── Daily Digest ─────────────────────────────────────────────────────

    async def _maybe_post_digest(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = self.state["daily"]

        if daily["date"] == today:
            return

        if daily["date"] and daily["date"] != today:
            await self._post_digest(daily)

        self.state["daily"] = new_daily_stats()
        self.state["last_digest"] = daily["date"]

    async def _post_digest(self, daily):
        date          = daily["date"]
        games         = daily.get("games", 0)
        wins          = daily.get("wins", 0)
        deaths        = daily.get("deaths", 0)
        registrations = daily.get("registrations", 0)
        runes         = daily.get("runes", 0)
        players       = daily.get("players", [])
        notable       = daily.get("notable", [])

        if games == 0 and registrations == 0:
            return

        desc_parts = []
        if games > 0:
            win_rate = f" ({wins/games*100:.0f}% win rate)" if wins > 0 else ""
            desc_parts.append(f"**{games}** games played{win_rate}")
        if wins > 0:
            desc_parts.append(f"**{wins}** victories \U0001f3c6")
        if deaths > 0:
            desc_parts.append(f"**{deaths}** deaths \U0001f480")
        if runes > 0:
            desc_parts.append(f"**{runes}** runes collected \U0001f538")
        if registrations > 0:
            s = "s" if registrations != 1 else ""
            desc_parts.append(f"**{registrations}** new player{s} joined \U0001f44b")
        if players:
            s = "s" if len(players) != 1 else ""
            desc_parts.append(f"**{len(players)}** unique adventurer{s}")

        description = "\n".join(desc_parts)
        if notable:
            description += "\n\n**Highlights:**\n" + "\n".join(notable[:10])

        fields = []
        recs = self.state.get("records", {})
        rec_parts = []
        for key, label in [
            ("highest_score", "Highest Score"),
            ("fastest_realtime", "Fastest Win"),
            ("fastest_turns", "Fewest Turns"),
        ]:
            rec = recs.get(key, {})
            if rec.get("player"):
                val = rec["value"]
                if key == "highest_score":
                    val_str = format_score(val)
                elif key == "fastest_realtime":
                    val_str = format_duration(val)
                else:
                    val_str = format_turns(val)
                rec_parts.append(f"**{label}:** {val_str} by {rec['player']} ({rec['combo']})")

        if rec_parts:
            fields.append({
                "name": "\U0001f3c5 Server Records",
                "value": "\n".join(rec_parts),
                "inline": False,
            })

        embed = make_embed(
            title=f"\U0001f4ca Daily Digest \u2014 {date}",
            description=description,
            color=COLOR_DIGEST,
            fields=fields if fields else None,
        )
        await self.send_embed(embed)
        log.info(f"Posted daily digest for {date}")

    # ── Startup Message ──────────────────────────────────────────────────

    async def _send_startup(self):
        versions = ", ".join(version_label(v) for _, v in VERSION_DIRS)
        total = self.state.get("total_games", 0)
        wins = self.state.get("total_wins", 0)
        combos = len(self.state.get("combo_firsts", {}))

        desc = f"Monitoring all game versions on **{SERVER_NAME}**."
        if total > 0:
            desc += f"\n\n**All-time:** {total:,} games, {wins:,} wins, {combos} winning combos"

        embed = make_embed(
            title=f"\U0001f7e2 {SERVER_NAME} Bot Online",
            description=desc,
            color=COLOR_ONLINE,
            fields=[
                {"name": "Versions", "value": versions, "inline": True},
                {"name": "Play Now", "value": f"[WebTiles]({SERVER_URL})", "inline": True},
            ],
        )
        await self.send_embed(embed)


# ═══════════════════════════════════════════════════════════════════════════
# Bot Instance & Slash Commands
# ═══════════════════════════════════════════════════════════════════════════

bot = WebTilesBot()


async def player_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete player names from known players."""
    players = list(interaction.client.state.get("player_stats", {}).keys())
    return [
        app_commands.Choice(name=p, value=p)
        for p in players
        if current.lower() in p.lower()
    ][:25]


@bot.tree.command(name="stats", description="View player statistics")
@app_commands.describe(player="Player name")
@app_commands.autocomplete(player=player_autocomplete)
async def cmd_stats(interaction: discord.Interaction, player: str):
    state = interaction.client.state

    # Case-insensitive lookup
    ps = None
    matched_name = player
    for name, data in state.get("player_stats", {}).items():
        if name.lower() == player.lower():
            ps = data
            matched_name = name
            break

    if not ps:
        await interaction.response.send_message(
            f"No stats found for **{player}**. Check the spelling?",
            ephemeral=True,
        )
        return

    games = ps.get("games", 0)
    wins = ps.get("wins", 0)
    win_rate = f"{wins/games*100:.1f}%" if games > 0 else "0%"
    best_score = format_score(ps.get("best_score", 0))
    best_combo = ps.get("best_combo", "?")
    streak = ps.get("streak", 0)
    best_streak = ps.get("best_streak", 0)

    embed = make_embed(
        title=f"\U0001f4ca {matched_name}'s Stats",
        color=COLOR_STATS,
        fields=[
            {"name": "Games",        "value": str(games),      "inline": True},
            {"name": "Wins",         "value": str(wins),       "inline": True},
            {"name": "Win Rate",     "value": win_rate,        "inline": True},
            {"name": "Best Score",   "value": best_score,      "inline": True},
            {"name": "Best Combo",   "value": best_combo,      "inline": True},
            {"name": "Best Streak",  "value": str(best_streak), "inline": True},
        ],
        url=morgue_url(matched_name),
    )

    if streak > 0:
        embed.add_field(
            name="\U0001f525 Current Streak",
            value=f"{streak} win{'s' if streak != 1 else ''} in a row!",
            inline=False,
        )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description=f"Top scores on {SERVER_NAME}")
async def cmd_leaderboard(interaction: discord.Interaction):
    state = interaction.client.state
    top = state.get("top_scores", [])

    if not top:
        await interaction.response.send_message(
            "No scores recorded yet!", ephemeral=True
        )
        return

    lines = []
    for i, entry in enumerate(top[:10], 1):
        medal = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}.get(i, f"**{i}.**")
        lines.append(
            f"{medal} **{format_score(entry['score'])}** \u2014 "
            f"{entry['player']} ({entry['combo']}, {version_label(entry['version'])})"
        )

    embed = make_embed(
        title=f"\U0001f3c6 {SERVER_NAME} Leaderboard \u2014 Top 10",
        description="\n".join(lines),
        color=COLOR_WIN,
        url=f"{SERVER_URL}/scores/",
    )

    total = state.get("total_games", 0)
    total_wins = state.get("total_wins", 0)
    embed.set_footer(text=f"{total:,} games played, {total_wins:,} wins \u2014 {SERVER_NAME} \u2022 {SERVER_HOST}")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="records", description=f"{SERVER_NAME} server records")
async def cmd_records(interaction: discord.Interaction):
    state = interaction.client.state
    recs = state.get("records", {})

    lines = []
    for key, label, formatter in [
        ("highest_score",    "Highest Score",  lambda v: format_score(v)),
        ("fastest_realtime", "Fastest Win",    lambda v: format_duration(v)),
        ("fastest_turns",    "Fewest Turns",   lambda v: format_turns(v)),
        ("most_runes",       "Most Runes",     lambda v: str(v)),
    ]:
        rec = recs.get(key, {})
        if rec.get("player") and rec.get("value", 0) > 0:
            val = rec["value"]
            if key == "fastest_realtime" and val >= 999999999:
                continue
            if key == "fastest_turns" and val >= 999999999:
                continue
            lines.append(
                f"\U0001f3c5 **{label}:** {formatter(val)}\n"
                f"\u2003by **{rec['player']}** ({rec['combo']}, {version_label(rec['version'])})"
            )

    combos = state.get("combo_firsts", {})
    if combos:
        lines.append(f"\n\u2b50 **Winning Combos:** {len(combos)} unique combos have won")

    if not lines:
        await interaction.response.send_message(
            "No records set yet \u2014 be the first!", ephemeral=True
        )
        return

    embed = make_embed(
        title=f"\U0001f3c5 {SERVER_NAME} Server Records",
        description="\n\n".join(lines),
        color=COLOR_RECORD,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="morgue", description="Link to a player's morgue files")
@app_commands.describe(player="Player name")
@app_commands.autocomplete(player=player_autocomplete)
async def cmd_morgue(interaction: discord.Interaction, player: str):
    embed = make_embed(
        title=f"\U0001f4dc {player}'s Files",
        color=COLOR_INFO,
        fields=[
            {"name": "Morgue Files", "value": f"[Browse]({SERVER_URL}/morgue/{player}/)", "inline": False},
            {"name": "RC Files", "value": f"[Browse]({SERVER_URL}/rcfiles/crawl-0.34/{player}.rc)", "inline": False},
            {"name": "TTYrecs", "value": f"[Browse]({SERVER_URL}/ttyrec/{player}/)", "inline": False},
        ],
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="info", description=f"{SERVER_NAME} server information")
async def cmd_info(interaction: discord.Interaction):
    state = interaction.client.state
    total = state.get("total_games", 0)
    total_wins = state.get("total_wins", 0)
    players = len(state.get("player_stats", {}))
    versions = ", ".join(version_label(v) for _, v in VERSION_DIRS)

    embed = make_embed(
        title=f"\U0001f3ae {SERVER_NAME} \u2014 Dungeon Crawl Stone Soup",
        description=(
            f"**Server:** {SERVER_HOST}\n"
            f"**Region:** {SERVER_REGION}\n"
            f"**Versions:** {versions}\n"
        ),
        color=COLOR_INFO,
        fields=[
            {"name": "WebTiles", "value": f"[Play Now]({SERVER_URL})", "inline": True},
            {"name": "SSH", "value": f"`ssh -p 222 crawl@{SERVER_HOST}`", "inline": True},
            {"name": "Scores", "value": f"[Leaderboard]({SERVER_URL}/scores/)", "inline": True},
            {"name": "Discord", "value": f"[Join](https://discord.gg/{DISCORD_INVITE})", "inline": True},
            {"name": "Total Games", "value": f"{total:,}", "inline": True},
            {"name": "Players", "value": f"{players:,}", "inline": True},
        ],
    )
    await interaction.response.send_message(embed=embed)


# ═══════════════════════════════════════════════════════════════════════════
# Discord Link & Role Commands
# ═══════════════════════════════════════════════════════════════════════════


@bot.tree.command(name=f"link-{SERVER_SLUG}", description=f"Link your Discord to your {SERVER_NAME} account for auto-roles")
@app_commands.describe(username=f"Your {SERVER_NAME} ({SERVER_HOST}) username")
async def cmd_link(interaction: discord.Interaction, username: str):
    discord_id = str(interaction.user.id)
    links = load_discord_links()

    # Check if already verified
    existing = links.get(discord_id)
    if existing and existing.get("verified"):
        await interaction.response.send_message(
            f"You're already linked as **{existing['username']}**. "
            f"Use `/unlink-{SERVER_SLUG}` first if you want to change accounts.",
            ephemeral=True,
        )
        return

    # Per-server linking: username must exist on THIS bot's server
    if not username_exists(username):
        await interaction.response.send_message(
            f"Username **{username}** not found on {SERVER_NAME}. "
            f"Check the spelling — it's case-sensitive.",
            ephemeral=True,
        )
        return

    # Check if someone else already claimed this username
    for did, info in links.items():
        if did != discord_id and info.get("username", "").lower() == username.lower() and info.get("verified"):
            await interaction.response.send_message(
                "That username is already linked to another Discord account.",
                ephemeral=True,
            )
            return

    # Generate time-limited verification code
    code = f"#discord-{secrets.token_hex(4).lower()}"
    links[discord_id] = {
        "username": username,
        "verified": False,
        "code": code,
        "code_expires": (datetime.now(timezone.utc).timestamp() + LINK_CODE_EXPIRY_SECONDS),
    }
    save_discord_links(links)

    embed = discord.Embed(
        title="\U0001f517 Discord Link — Verification Required",
        color=COLOR_ROLE,
        description=(
            f"To verify you own **{username}**, add this line to your RC file:\n\n"
            f"```\n{code}\n```\n\n"
            f"**How to add it:**\n"
            f"1. Go to [{SERVER_HOST}]({SERVER_URL})\n"
            f"2. Log in and click **Edit RC** (Settings icon) for any version\n"
            f"3. Paste `{code}` anywhere in the file and save\n"
            f"4. Come back here and run `/verify-{SERVER_SLUG}` within **5 minutes**\n\n"
            f"\u23f0 This code expires in **5 minutes**. It starts with `#` so it won't affect your config."
        ),
    )
    embed.set_footer(text=f"{SERVER_NAME} \u2022 {SERVER_HOST}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name=f"verify-{SERVER_SLUG}", description=f"Verify your {SERVER_NAME} account link (after adding code to RC file)")
async def cmd_verify(interaction: discord.Interaction):
    discord_id = str(interaction.user.id)
    links = load_discord_links()
    info = links.get(discord_id)

    if not info:
        await interaction.response.send_message(
            f"No pending link. Use `/link-{SERVER_SLUG} <username>` first.",
            ephemeral=True,
        )
        return

    if info.get("verified"):
        await interaction.response.send_message(
            f"You're already verified as **{info['username']}**!",
            ephemeral=True,
        )
        return

    # Check expiry
    expires = info.get("code_expires", 0)
    if datetime.now(timezone.utc).timestamp() > expires:
        del links[discord_id]
        save_discord_links(links)
        await interaction.response.send_message(
            f"Your verification code has **expired**. Run `/link-{SERVER_SLUG} <username>` again to get a new one.",
            ephemeral=True,
        )
        return

    username = info["username"]
    code = info["code"]

    await interaction.response.defer(ephemeral=True)

    # Per-server linking: only check this bot's server's RC files
    found = False
    rc_versions = ["crawl-0.34", "crawl-git", "crawl-0.33", "crawl-0.32", "crawl-0.31", "crawl-0.30"]
    for ver in rc_versions:
        rc_url = f"{SERVER_URL}/rcfiles/{ver}/{urllib.request.quote(username)}.rc"
        try:
            req = urllib.request.Request(rc_url, headers={"User-Agent": f"{SERVER_NAME}-Bot/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                rc_content = resp.read().decode("utf-8", errors="replace")
                if code in rc_content:
                    found = True
                    break
        except (urllib.error.URLError, OSError):
            continue

    if not found:
        await interaction.followup.send(
            f"Code `{code}` not found in any RC file for **{username}** on {SERVER_HOST}.\n\n"
            f"Make sure you pasted `{code}` in your RC file and saved it.",
            ephemeral=True,
        )
        return

    # Verified!
    info["verified"] = True
    info["verified_at"] = datetime.now(timezone.utc).isoformat()
    del info["code"]
    del info["code_expires"]
    save_discord_links(links)

    # Sync roles immediately
    stats = fetch_player_stats(username)
    added_roles = []
    if stats and GUILD_ID:
        guild = interaction.client.get_guild(GUILD_ID)
        if guild:
            member = guild.get_member(interaction.user.id)
            if not member:
                try:
                    member = await guild.fetch_member(interaction.user.id)
                except discord.NotFound:
                    member = None
            if member:
                added_roles = await interaction.client.sync_member_roles(member, stats)
                log.info(f"[link] Synced {len(added_roles)} roles for {username}")
            else:
                log.warning(f"[link] Could not find member {interaction.user.id} in guild")
    elif not stats:
        log.warning(f"[link] No stats found for {username}")

    role_text = ""
    if added_roles:
        role_text = f"\n\n**Roles earned:** {', '.join(added_roles)}"

    other_link_hint = (
        f"\n\nIf you also play on {OTHER_SERVER_NAME}, link that account separately with `/link-{OTHER_SERVER_SLUG}`."
        if OTHER_SERVER_NAME and OTHER_SERVER_SLUG else ""
    )
    await interaction.followup.send(
        f"\u2705 **Linked!** Your Discord is now linked to **{username}** on {SERVER_NAME}.\n"
        f"Your roles will update automatically as you play.{role_text}\n\n"
        f"You can remove the code from your RC file now.{other_link_hint}",
        ephemeral=True,
    )
    log.info(f"[link] {interaction.user} linked as {username}")


@bot.tree.command(name=f"unlink-{SERVER_SLUG}", description=f"Unlink your Discord from your {SERVER_NAME} account")
async def cmd_unlink(interaction: discord.Interaction):
    discord_id = str(interaction.user.id)
    links = load_discord_links()

    if discord_id not in links:
        await interaction.response.send_message(
            f"You don't have a linked {SERVER_NAME} account.", ephemeral=True
        )
        return

    username = links[discord_id].get("username", "unknown")
    was_verified = links[discord_id].get("verified", False)
    del links[discord_id]
    save_discord_links(links)

    # Remove DCSS roles
    if was_verified and GUILD_ID:
        role_state = load_role_state()
        guild = interaction.client.get_guild(GUILD_ID)
        if guild:
            member = guild.get_member(interaction.user.id)
            if member:
                for rdef in DCSS_ROLE_DEFS + [LINKED_ROLE_DEF]:
                    role_id = role_state.get(rdef["key"])
                    if role_id and member.get_role(int(role_id)):
                        try:
                            await member.remove_roles(
                                discord.Object(id=int(role_id)), reason=f"{SERVER_NAME} unlink"
                            )
                        except discord.HTTPException:
                            pass

    await interaction.response.send_message(
        f"Unlinked from **{username}**. All DCSS roles have been removed.",
        ephemeral=True,
    )
    log.info(f"[link] {interaction.user} unlinked from {username}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


def main():
    if not BOT_TOKEN:
        log.critical("DISCORD_BOT_TOKEN not set!")
        sys.exit(1)
    if not CHANNEL_ID:
        log.warning("DISCORD_CHANNEL_ID not set \u2014 notifications will be disabled")

    log.info(f"Starting {SERVER_NAME} Discord bot")
    log.info(f"Watching {len(VERSION_DIRS)} versions, polling every {POLL_INTERVAL}s")
    log.info(f"Notification channel: {CHANNEL_ID}")
    log.info(f"Guild ID: {GUILD_ID or 'global (slow sync)'}")

    bot.run(BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
