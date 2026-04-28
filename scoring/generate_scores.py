#!/usr/bin/env python3
"""
DCSS leaderboard generator.
Reads the DCSS xlog format, produces a static HTML scoreboard,
generates banner-stats.json for the lobby banner,
generates stats.html with detailed player/race/class/god statistics,
and refreshes every UPDATE_INTERVAL seconds.
"""

import json
import os
import re
import sqlite3
import time
import datetime
from collections import defaultdict
from jinja2 import Template

LOGFILE          = os.environ.get("LOGFILE",          "/data/logfiles/logfile")
MILESTONES       = os.environ.get("MILESTONES",       "/data/milestones/milestones")
MORGUE_URL       = os.environ.get("MORGUE_URL",       "/morgue")
OUTPUT_DIR       = os.environ.get("OUTPUT_DIR",       "/scores")
UPDATE_INTERVAL  = int(os.environ.get("UPDATE_INTERVAL", "60"))
SERVER_ABBR      = os.environ.get("SERVER_ABBR", "MYSRV")
SERVER_URL       = os.environ.get("SERVER_URL",  "https://my-server.example.com")
SERVER_HOST      = SERVER_URL.replace("https://", "").replace("http://", "")


def _apply_server_branding(tmpl: str) -> str:
    """Substitute baked-in placeholder references with this server's identity.
    Order matters: replace the longer URL form first so the bare host doesn't
    eat the protocol prefix."""
    return (
        tmpl
        .replace("__SERVER_URL__", SERVER_URL)
        .replace("__SERVER_HOST__", SERVER_HOST)
        .replace("__SERVER_ABBR__", SERVER_ABBR)
    )

# All known save directories (each contains a 'logfile' and 'milestones')
ALL_SAVE_DIRS = [
    ("/data/saves",       "0.34"),
    ("/data/saves-trunk", "trunk"),
    ("/data/saves-0.33",  "0.33"),
    ("/data/saves-0.32",  "0.32"),
    ("/data/saves-0.31",  "0.31"),
    ("/data/saves-0.30",  "0.30"),
]

# Milestone types to filter out (boring/noisy)
BORING_MILESTONES = {"begin", "chargen", "identified"}

# ── xlog parser ──────────────────────────────────────────────────────────────

def parse_xlog_line(line: str) -> dict:
    """Parse a colon-separated DCSS xlog line into a dict.
    Handles colons inside values (e.g. place=D:3) by splitting only
    on ':' that are immediately followed by a 'key=' pattern."""
    entry: dict = {}
    parts = re.split(r":(?=[a-zA-Z_%]+=)", line.strip())
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            entry[k.strip()] = v.strip()
    return entry


def load_games(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    games = []
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                g = parse_xlog_line(line)
                if g:
                    games.append(g)
    return games


# ── helpers ───────────────────────────────────────────────────────────────────

def is_win(g: dict) -> bool:
    return g.get("ktyp", "") in ("winning", "winner") or \
           "escaped" in g.get("tmsg", "").lower()


def score(g: dict) -> int:
    try:
        return int(g.get("sc", 0))
    except ValueError:
        return 0


def fmt_score(n: int) -> str:
    return f"{n:,}"


def combo(g: dict) -> str:
    race = g.get("race", "?")[:2]
    cls  = g.get("cls",  "?")[:2]
    return f"{race}{cls}"


def _parse_ts_components(ts_raw: str) -> tuple[int, int, int, int, int, int] | None:
    """Extract year, month, day, hour, minute, second as integers from a raw
    DCSS timestamp string.  Returns None if the string is too short or
    contains non-numeric data."""
    ts = ts_raw.rstrip("SD")
    if len(ts) < 14:
        return None
    try:
        return (int(ts[0:4]), int(ts[4:6]), int(ts[6:8]),
                int(ts[8:10]), int(ts[10:12]), int(ts[12:14]))
    except ValueError:
        return None


def _detect_month_bug() -> bool:
    """Auto-detect the DCSS xlog tm_mon off-by-one bug by comparing the
    newest xlog timestamp against the logfile's filesystem mtime."""
    for save_dir, _ in ALL_SAVE_DIRS:
        logpath = os.path.join(save_dir, "logfile")
        if not os.path.exists(logpath) or os.path.getsize(logpath) == 0:
            continue
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(logpath))
            with open(logpath, "rb") as f:
                # Read last line
                f.seek(0, 2)
                pos = f.tell()
                while pos > 0:
                    pos -= 1
                    f.seek(pos)
                    if f.read(1) == b"\n" and pos < f.seek(0, 2) - 1:
                        break
                f.seek(max(pos, 0))
                last_line = f.read().decode("utf-8", errors="replace").strip()
            # Parse the raw end timestamp (no correction)
            for part in re.split(r":(?=[a-zA-Z_%]+=)", last_line):
                if part.startswith("end="):
                    comps = _parse_ts_components(part[4:])
                    if not comps:
                        continue
                    year, month, day, hour, minute, second = comps
                    # Clamp day to 28 so raw (possibly invalid) dates can
                    # still be compared against mtime for bug detection
                    dt = datetime.datetime(year, month, min(day, 28), hour, minute, second)
                    diff = abs((mtime - dt).days)
                    # If xlog timestamp is ~28-32 days behind mtime, bug is present
                    if 20 < diff < 40:
                        print(f"[INFO] Detected xlog month bug (xlog={dt.date()}, file mtime={mtime.date()}, diff={diff}d)")
                        return True
                    else:
                        print(f"[INFO] No xlog month bug detected (xlog={dt.date()}, file mtime={mtime.date()}, diff={diff}d)")
                        return False
        except Exception as exc:
            print(f"[WARN] Month bug detection failed for {logpath}: {exc}")
            continue
    return False  # No data to check, assume no bug


# Detect once at startup
_MONTH_BUG = _detect_month_bug()


def parse_dcss_ts(s: str) -> datetime.datetime | None:
    """Parse a DCSS timestamp, auto-correcting for the tm_mon off-by-one bug
    if detected at startup.

    Components are extracted as integers BEFORE constructing a datetime so
    that impossible raw dates (e.g. Feb 31 from the month bug) don't cause
    strptime to fail."""
    comps = _parse_ts_components(s)
    if not comps:
        return None
    year, month, day, hour, minute, second = comps
    try:
        if _MONTH_BUG:
            if month < 12:
                month += 1
            else:
                year += 1
                month = 1
        return datetime.datetime(year, month, day, hour, minute, second)
    except Exception:
        return None


def fmt_date(s: str) -> str:
    dt = parse_dcss_ts(s)
    if dt:
        return dt.strftime("%Y-%m-%d %H:%M")
    return s[:16] if s else "?"


def fmt_dur(s: str) -> str:
    try:
        sec = int(s)
        h, rem = divmod(sec, 3600)
        m, s2  = divmod(rem, 60)
        return f"{h}h{m:02d}m" if h else f"{m}m{s2:02d}s"
    except Exception:
        return "?"


def fmt_relative_time(ts_str: str) -> str:
    dt = parse_dcss_ts(ts_str)
    if not dt:
        return "?"
    delta = datetime.datetime.now() - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    days = secs // 86400
    return f"{days}d ago"


def outcome(g: dict) -> str:
    if is_win(g):
        return "WON"
    return g.get("tmsg", g.get("killer", "unknown"))[:60]


def outcome_class(g: dict) -> str:
    return "win" if is_win(g) else "death"


def morgue_link(g: dict) -> str:
    name  = g.get("name", "")
    ts    = g.get("end",  "")
    if not name or not ts:
        return ""
    # Build direct link to morgue file: morgue-{name}-{YYYYMMDD-HHMMSS}.txt
    # Morgue filenames use correct months, so apply month-bug correction
    dt = parse_dcss_ts(ts)
    if dt:
        fname = f"morgue-{name}-{dt.strftime('%Y%m%d-%H%M%S')}.txt"
        return f"{MORGUE_URL}/{name}/{fname}"
    return f"{MORGUE_URL}/{name}/"


# ── stats builders ───────────────────────────────────────────────────────────

def build_stats(games: list[dict]) -> dict:
    top_scores   = sorted(games, key=score, reverse=True)[:15]
    recent_wins  = [g for g in reversed(games) if is_win(g)][:10]
    recent_games = list(reversed(games))[:25]

    by_player: dict = defaultdict(lambda: {
        "games": 0, "wins": 0, "best": 0, "total_score": 0,
        "best_xl": 0, "name": ""
    })
    for g in games:
        n = g.get("name", "?")
        p = by_player[n]
        p["name"]  = n
        p["games"] += 1
        if is_win(g):
            p["wins"] += 1
        sc = score(g)
        if sc > p["best"]:
            p["best"] = sc
        p["total_score"] += sc
        xl = int(g.get("xl", 0) or 0)
        if xl > p["best_xl"]:
            p["best_xl"] = xl

    player_list = sorted(by_player.values(), key=lambda p: p["best"], reverse=True)

    return {
        "top_scores":   top_scores,
        "recent_wins":  recent_wins,
        "recent_games": recent_games,
        "players":      player_list,
        "total_games":  len(games),
        "total_wins":   sum(1 for g in games if is_win(g)),
        "updated":      datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


# ── DCSS tips (rotated daily) ────────────────────────────────────────────────

DCSS_TIPS = []  # Disabled — tips had inaccuracies

# ── Banner stats JSON builder ────────────────────────────────────────────────

def load_all_games() -> list[dict]:
    """Load games from all known logfile locations across versions.
    Returns games sorted chronologically by end time."""
    all_games = []
    for save_dir, version in ALL_SAVE_DIRS:
        logpath = os.path.join(save_dir, "logfile")
        if os.path.exists(logpath):
            games = load_games(logpath)
            for g in games:
                g["_version"] = version
            all_games.extend(games)
    # Sort by end timestamp so chronological iteration works correctly
    all_games.sort(key=lambda g: g.get("end", ""))
    return all_games


def load_all_milestones() -> list[dict]:
    """Load milestones from all known save directories across versions."""
    all_ms = []
    for save_dir, version in ALL_SAVE_DIRS:
        ms_path = os.path.join(save_dir, "milestones")
        if os.path.exists(ms_path):
            entries = load_games(ms_path)
            for m in entries:
                m["_version"] = version
            all_ms.extend(entries)
    all_ms.sort(key=lambda m: m.get("time", ""))
    return all_ms


def build_recent_milestones(all_milestones: list[dict], limit: int = 15) -> list[dict]:
    """Return the most recent interesting milestones for display."""
    result = []
    for m in reversed(all_milestones):
        if m.get("type", "") in BORING_MILESTONES:
            continue
        result.append({
            "name": m.get("name", "?"),
            "combo": combo(m),
            "xl": m.get("xl", "?"),
            "milestone": m.get("milestone", "?"),
            "place": m.get("place", "").replace("::", ":"),
            "god": m.get("god", ""),
            "time_ago": fmt_relative_time(m.get("time", "")),
            "version": m.get("_version", "?"),
        })
        if len(result) >= limit:
            break
    return result


def build_streaks(all_games: list[dict]) -> list[dict]:
    """Calculate consecutive win streaks per player."""
    # Group games by player, sorted chronologically
    by_player: dict[str, list[dict]] = defaultdict(list)
    for g in all_games:
        name = g.get("name", "")
        if name:
            by_player[name].append(g)

    all_streaks = []
    for name, games in by_player.items():
        games.sort(key=lambda g: g.get("end", ""))
        current_streak = []
        for g in games:
            if is_win(g):
                current_streak.append(g)
            else:
                if len(current_streak) >= 2:
                    all_streaks.append({
                        "name": name,
                        "length": len(current_streak),
                        "games": [combo(g) for g in current_streak],
                        "start": fmt_date(current_streak[0].get("end", "")),
                        "end": fmt_date(current_streak[-1].get("end", "")),
                        "active": False,
                    })
                current_streak = []
        # Check if streak is still active (ended on a win)
        if len(current_streak) >= 2:
            all_streaks.append({
                "name": name,
                "length": len(current_streak),
                "games": [combo(g) for g in current_streak],
                "start": fmt_date(current_streak[0].get("end", "")),
                "end": fmt_date(current_streak[-1].get("end", "")),
                "active": True,
            })

    all_streaks.sort(key=lambda s: s["length"], reverse=True)
    return all_streaks[:20]


def build_fastest_wins(all_games: list[dict]) -> tuple[list[dict], list[dict]]:
    """Build top 10 fastest wins by real time and by turn count."""
    wins = [g for g in all_games if is_win(g)]

    # Fastest by real time (dur field, in seconds)
    by_time = sorted(wins, key=lambda g: int(g.get("dur", 999999999) or 999999999))[:10]
    fastest_time = []
    for g in by_time:
        fastest_time.append({
            "name": g.get("name", "?"),
            "race": g.get("race", "?"),
            "cls": g.get("cls", "?"),
            "god": g.get("god", "-"),
            "dur": fmt_dur(g.get("dur", "0")),
            "turns": f"{int(g.get('turn', 0) or 0):,}",
            "score_fmt": fmt_score(score(g)),
            "runes": g.get("urune", "0"),
            "date": fmt_date(g.get("end", "")),
            "morgue": morgue_link(g),
        })

    # Fastest by turn count
    by_turns = sorted(wins, key=lambda g: int(g.get("turn", 999999999) or 999999999))[:10]
    fastest_turns = []
    for g in by_turns:
        fastest_turns.append({
            "name": g.get("name", "?"),
            "race": g.get("race", "?"),
            "cls": g.get("cls", "?"),
            "god": g.get("god", "-"),
            "dur": fmt_dur(g.get("dur", "0")),
            "turns": f"{int(g.get('turn', 0) or 0):,}",
            "score_fmt": fmt_score(score(g)),
            "runes": g.get("urune", "0"),
            "date": fmt_date(g.get("end", "")),
            "morgue": morgue_link(g),
        })

    return fastest_time, fastest_turns


def build_top_killers(all_games: list[dict]) -> list[dict]:
    """Count deaths by killer, excluding quits and leaves."""
    kills: dict[str, dict] = defaultdict(lambda: {"count": 0, "last_victim": None})
    total_deaths = 0

    for g in all_games:
        if is_win(g):
            continue
        ktyp = g.get("ktyp", "")
        if ktyp in ("quitting", "leaving"):
            continue
        killer = g.get("killer", "")
        if not killer:
            killer = g.get("kaux", "unknown")
        if not killer:
            continue
        total_deaths += 1
        kills[killer]["count"] += 1
        kills[killer]["last_victim"] = g

    killer_list = []
    for killer, data in kills.items():
        pct = (data["count"] / total_deaths * 100) if total_deaths else 0
        victim_g = data["last_victim"]
        killer_list.append({
            "name": killer,
            "count": data["count"],
            "pct": f"{pct:.1f}",
            "last_victim": victim_g.get("name", "?") if victim_g else "?",
            "last_victim_morgue": morgue_link(victim_g) if victim_g else "",
        })

    killer_list.sort(key=lambda k: k["count"], reverse=True)
    return killer_list[:10]


def parse_end_time(g: dict) -> datetime.datetime | None:
    """Parse end timestamp from a game entry."""
    return parse_dcss_ts(g.get("end", ""))


def game_to_json(g: dict, include_death: bool = False) -> dict:
    """Convert a game dict to a JSON-safe dict for the banner."""
    result = {
        "name": g.get("name", "?"),
        "race": g.get("race", "?"),
        "cls": g.get("cls", "?"),
        "xl": g.get("xl", "?"),
        "score": fmt_score(score(g)),
        "dur": fmt_dur(g.get("dur", "0")),
        "runes": g.get("urune", "0"),
        "god": g.get("god", ""),
        "place": g.get("place", "?").replace("::", ":"),
        "end": fmt_date(g.get("end", "")),
        "version": g.get("_version", "?"),
        "morgue_url": morgue_link(g),
    }
    if include_death:
        result["killer"] = g.get("killer", g.get("kaux", "unknown"))[:80]
        result["tmsg"] = g.get("tmsg", "")[:120]
    return result


def _get_newest_user() -> str | None:
    """Return the username of the most recently registered player."""
    db = "/data/passwd.db3"
    if not os.path.exists(db):
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        row = conn.execute("SELECT username FROM dglusers ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def build_banner_stats(all_games: list[dict]) -> dict:
    """Build the banner stats JSON object."""
    now = datetime.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - datetime.timedelta(days=1)

    # ── Latest win (most recent across all versions) ──
    # all_games is sorted chronologically, so reversed gives most recent first
    latest_win = None
    for g in reversed(all_games):
        if is_win(g):
            latest_win = g
            break

    # ── Death of the Day: highest XL non-win death in last 24h ──
    # Falls back to last 7 days if no deaths today
    death_of_day = None
    death_of_day_xl = -1
    fallback_death = None
    fallback_death_xl = -1
    week_ago = now - datetime.timedelta(days=7)

    for g in reversed(all_games):
        if is_win(g):
            continue
        t = parse_end_time(g)
        if not t:
            continue
        if t < week_ago:
            break  # games are chronological, older ones won't match
        xl = int(g.get("xl", 0) or 0)
        if t >= yesterday_start:
            if xl > death_of_day_xl:
                death_of_day = g
                death_of_day_xl = xl
        elif xl > fallback_death_xl:
            fallback_death = g
            fallback_death_xl = xl

    # If timestamp-based filtering found nothing, fall back to most recent highest-XL death
    if not death_of_day and not fallback_death:
        for g in reversed(all_games):
            if is_win(g):
                continue
            xl = int(g.get("xl", 0) or 0)
            if xl > fallback_death_xl:
                fallback_death = g
                fallback_death_xl = xl
            if len([x for x in all_games if not is_win(x)]) > 10:
                break  # only check recent games

    chosen_death = death_of_day if death_of_day else fallback_death
    death_label = "Death of the Day" if death_of_day else "Notable Death"

    # ── Server stats ──
    unique_players = set()
    games_today = 0
    games_this_week = 0
    week_start = now - datetime.timedelta(days=7)

    any_recent = False
    for g in all_games:
        unique_players.add(g.get("name", "?"))
        t = parse_end_time(g)
        if t:
            if t >= today_start:
                games_today += 1
                any_recent = True
            if t >= week_start:
                games_this_week += 1
                any_recent = True

    # If timestamps are all in the past (DCSS clock bug), count all games as recent
    if not any_recent and len(all_games) > 0:
        games_today = len(all_games)
        games_this_week = len(all_games)

    # ── Tip of the day (disabled) ──
    tip = None

    # ── Recent deaths feed (last 5 interesting deaths, XL >= 5) ──
    recent_deaths = []
    for g in reversed(all_games):
        if is_win(g):
            continue
        xl = int(g.get("xl", 0) or 0)
        if xl < 5:
            continue
        recent_deaths.append(game_to_json(g, include_death=True))
        if len(recent_deaths) >= 5:
            break

    result = {
        "latest_win": game_to_json(latest_win) if latest_win else None,
        "death_of_day": game_to_json(chosen_death, include_death=True) if chosen_death else None,
        "death_label": death_label,
        "total_games": len(all_games),
        "total_wins": sum(1 for g in all_games if is_win(g)),
        "unique_players": len(unique_players),
        "games_today": games_today,
        "games_this_week": games_this_week,
        "tip": tip,
        "motd": "West Coast server is live \u2014 closer to the Orb, closer to your grave." if SERVER_ABBR == "CRG" else "South America server is live \u2014 lower ping, faster deaths.",
        "newest_user": _get_newest_user(),
        "recent_deaths": recent_deaths,
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return result


def write_banner_stats(all_games: list[dict]):
    """Write banner-stats.json for the lobby banner to consume."""
    stats = build_banner_stats(all_games)
    out = os.path.join(OUTPUT_DIR, "banner-stats.json")
    tmp = out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(stats, fh, separators=(",", ":"))
    os.replace(tmp, out)


# ── Detailed stats builder (for stats.html) ────────────────────────────────

def build_detailed_stats(all_games: list[dict]) -> dict:
    """Build rich statistics from all games across all versions."""
    now = datetime.datetime.now()

    # ── Per-player stats ──
    by_player: dict = defaultdict(lambda: {
        "name": "", "games": 0, "wins": 0, "best_score": 0,
        "best_xl": 0, "total_score": 0, "races": defaultdict(int),
        "classes": defaultdict(int), "gods": defaultdict(int),
        "total_dur": 0,
    })
    for g in all_games:
        n = g.get("name", "?")
        p = by_player[n]
        p["name"] = n
        p["games"] += 1
        if is_win(g):
            p["wins"] += 1
        sc = score(g)
        if sc > p["best_score"]:
            p["best_score"] = sc
        p["total_score"] += sc
        xl = int(g.get("xl", 0) or 0)
        if xl > p["best_xl"]:
            p["best_xl"] = xl
        race = g.get("race", "")
        cls = g.get("cls", "")
        god = g.get("god", "")
        if race:
            p["races"][race] += 1
        if cls:
            p["classes"][cls] += 1
        if god:
            p["gods"][god] += 1
        try:
            p["total_dur"] += int(g.get("dur", 0) or 0)
        except (ValueError, TypeError):
            pass

    player_list = []
    for p in by_player.values():
        fav_race = max(p["races"], key=p["races"].get) if p["races"] else "-"
        fav_class = max(p["classes"], key=p["classes"].get) if p["classes"] else "-"
        fav_god = max(p["gods"], key=p["gods"].get) if p["gods"] else "-"
        win_rate = (p["wins"] / p["games"] * 100) if p["games"] else 0
        player_list.append({
            "name": p["name"],
            "games": p["games"],
            "wins": p["wins"],
            "win_rate": f"{win_rate:.1f}",
            "best_score": p["best_score"],
            "best_score_fmt": fmt_score(p["best_score"]),
            "best_xl": p["best_xl"],
            "fav_race": fav_race,
            "fav_class": fav_class,
            "fav_god": fav_god,
            "playtime": fmt_dur(str(p["total_dur"])),
        })
    player_list.sort(key=lambda x: x["best_score"], reverse=True)

    # ── Per-race stats ──
    by_race: dict = defaultdict(lambda: {"games": 0, "wins": 0})
    for g in all_games:
        race = g.get("race", "")
        if not race:
            continue
        by_race[race]["games"] += 1
        if is_win(g):
            by_race[race]["wins"] += 1
    race_list = []
    for race, data in by_race.items():
        wr = (data["wins"] / data["games"] * 100) if data["games"] else 0
        race_list.append({
            "name": race, "games": data["games"],
            "wins": data["wins"], "win_rate": f"{wr:.1f}",
        })
    race_list.sort(key=lambda x: float(x["win_rate"]), reverse=True)

    # ── Per-class stats ──
    by_class: dict = defaultdict(lambda: {"games": 0, "wins": 0})
    for g in all_games:
        cls = g.get("cls", "")
        if not cls:
            continue
        by_class[cls]["games"] += 1
        if is_win(g):
            by_class[cls]["wins"] += 1
    class_list = []
    for cls, data in by_class.items():
        wr = (data["wins"] / data["games"] * 100) if data["games"] else 0
        class_list.append({
            "name": cls, "games": data["games"],
            "wins": data["wins"], "win_rate": f"{wr:.1f}",
        })
    class_list.sort(key=lambda x: float(x["win_rate"]), reverse=True)

    # ── Per-god stats ──
    by_god: dict = defaultdict(lambda: {"games": 0, "wins": 0})
    for g in all_games:
        god = g.get("god", "")
        if not god:
            continue
        by_god[god]["games"] += 1
        if is_win(g):
            by_god[god]["wins"] += 1
    god_list = []
    for god, data in by_god.items():
        wr = (data["wins"] / data["games"] * 100) if data["games"] else 0
        god_list.append({
            "name": god, "games": data["games"],
            "wins": data["wins"], "win_rate": f"{wr:.1f}",
        })
    god_list.sort(key=lambda x: float(x["win_rate"]), reverse=True)

    # ── Recent wins (last 10) ──
    recent_wins = []
    for g in reversed(all_games):
        if is_win(g):
            recent_wins.append({
                "name": g.get("name", "?"),
                "race": g.get("race", "?"),
                "cls": g.get("cls", "?"),
                "xl": g.get("xl", "?"),
                "score_fmt": fmt_score(score(g)),
                "god": g.get("god", "-"),
                "runes": g.get("urune", "0"),
                "dur": fmt_dur(g.get("dur", "0")),
                "turns": g.get("turn", "?"),
                "date": fmt_date(g.get("end", "")),
                "version": g.get("_version", "?"),
                "morgue": morgue_link(g),
            })
            if len(recent_wins) >= 10:
                break

    # ── Recent notable deaths (last 10 with XL >= 10) ──
    recent_deaths = []
    for g in reversed(all_games):
        if is_win(g):
            continue
        xl = int(g.get("xl", 0) or 0)
        if xl < 10:
            continue
        recent_deaths.append({
            "name": g.get("name", "?"),
            "race": g.get("race", "?"),
            "cls": g.get("cls", "?"),
            "xl": xl,
            "score_fmt": fmt_score(score(g)),
            "god": g.get("god", "-"),
            "place": g.get("place", "?").replace("::", ":"),
            "killer": g.get("tmsg", g.get("killer", "unknown"))[:60],
            "date": fmt_date(g.get("end", "")),
            "version": g.get("_version", "?"),
            "morgue": morgue_link(g),
        })
        if len(recent_deaths) >= 10:
            break

    # ── Server records ──
    wins_only = [g for g in all_games if is_win(g)]

    fastest_win = None
    if wins_only:
        fastest_win_g = min(wins_only, key=lambda g: int(g.get("dur", 999999999) or 999999999))
        fastest_win = {
            "name": fastest_win_g.get("name", "?"),
            "combo": f"{fastest_win_g.get('race', '?')} {fastest_win_g.get('cls', '?')}",
            "dur": fmt_dur(fastest_win_g.get("dur", "0")),
            "turns": fastest_win_g.get("turn", "?"),
            "date": fmt_date(fastest_win_g.get("end", "")),
        }

    highest_score = None
    if all_games:
        hs_g = max(all_games, key=score)
        highest_score = {
            "name": hs_g.get("name", "?"),
            "combo": f"{hs_g.get('race', '?')} {hs_g.get('cls', '?')}",
            "score_fmt": fmt_score(score(hs_g)),
            "win": is_win(hs_g),
            "date": fmt_date(hs_g.get("end", "")),
        }

    most_runes = None
    if all_games:
        mr_g = max(all_games, key=lambda g: int(g.get("urune", 0) or 0))
        runes_val = int(mr_g.get("urune", 0) or 0)
        if runes_val > 0:
            most_runes = {
                "name": mr_g.get("name", "?"),
                "combo": f"{mr_g.get('race', '?')} {mr_g.get('cls', '?')}",
                "runes": runes_val,
                "win": is_win(mr_g),
                "date": fmt_date(mr_g.get("end", "")),
            }

    most_turns_win = None
    if wins_only:
        mt_g = max(wins_only, key=lambda g: int(g.get("turn", 0) or 0))
        most_turns_win = {
            "name": mt_g.get("name", "?"),
            "combo": f"{mt_g.get('race', '?')} {mt_g.get('cls', '?')}",
            "turns": f"{int(mt_g.get('turn', 0) or 0):,}",
            "date": fmt_date(mt_g.get("end", "")),
        }

    fewest_turns_win = None
    if wins_only:
        ft_g = min(wins_only, key=lambda g: int(g.get("turn", 999999999) or 999999999))
        fewest_turns_win = {
            "name": ft_g.get("name", "?"),
            "combo": f"{ft_g.get('race', '?')} {ft_g.get('cls', '?')}",
            "turns": f"{int(ft_g.get('turn', 0) or 0):,}",
            "date": fmt_date(ft_g.get("end", "")),
        }

    total_games = len(all_games)
    total_wins = len(wins_only)
    unique_players = len(set(g.get("name", "?") for g in all_games))

    # ── Win Streaks ──
    streaks = build_streaks(all_games)

    # ── Fastest Wins ──
    fastest_by_time, fastest_by_turns = build_fastest_wins(all_games)

    # ── Top Killers ──
    top_killers = build_top_killers(all_games)

    return {
        "players": player_list,
        "races": race_list,
        "classes": class_list,
        "gods": god_list,
        "recent_wins": recent_wins,
        "recent_deaths": recent_deaths,
        "fastest_win": fastest_win,
        "highest_score": highest_score,
        "most_runes": most_runes,
        "most_turns_win": most_turns_win,
        "fewest_turns_win": fewest_turns_win,
        "streaks": streaks,
        "fastest_by_time": fastest_by_time,
        "fastest_by_turns": fastest_by_turns,
        "top_killers": top_killers,
        "total_games": total_games,
        "total_wins": total_wins,
        "unique_players": unique_players,
        "updated": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


# ── Stats page HTML template ──────────────────────────────────────────────

STATS_HTML_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{{ update_interval }}">
<title>Server Stats — DCSS — __SERVER_ABBR__</title>
<link rel="icon" href="/static/stone_soup_icon-32x32.png" type="image/png">
<style>
  @media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
  body { background: black; color: white; font-family: DejaVu Sans Mono, monospace; font-size: 16px; line-height: 1.6; margin: 0; padding: 1.5rem 2rem; }
  a { color: white; text-decoration: underline; }
  a:hover { color: lightgrey; }
  .header { margin-bottom: 0.5rem; }
  .nav { margin-bottom: 1rem; color: #888; }
  .nav a { color: #888; margin-right: 0.5rem; }
  .nav a:hover { color: white; }
  .nav a.active { color: white; }
  .nav .sep { color: #444; margin-right: 0.5rem; }
  .section-nav { margin-bottom: 1rem; padding: 0.5rem 0; border-bottom: 1px solid #222; position: sticky; top: 0; background: black; z-index: 3; font-size: 13px; }
  .section-nav a { color: #888; text-decoration: none; margin-right: 0.3rem; }
  .section-nav a:hover { color: #5fd7ff; }
  .section-nav .sn-sep { color: #333; margin-right: 0.3rem; }
  h1 { font-size: 16px; font-weight: normal; margin: 0.5rem 0; }
  h2 { font-size: 16px; font-weight: normal; color: #5fd7ff; margin: 1.5rem 0 0.5rem; border-bottom: 1px solid #222; padding-bottom: 0.3rem; scroll-margin-top: 3rem; }
  .stat-bar { margin-bottom: 1rem; color: #888; }
  .stat-bar span { color: white; }
  main { max-width: 1200px; flex: 1; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 1rem; }
  thead th { color: #888; text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #333; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
  thead { position: sticky; top: 2rem; background: black; z-index: 2; }
  tbody tr:hover { background: rgba(255,255,255,0.06); }
  td { padding: .3rem .5rem; border-bottom: 1px solid #1a1a1a; }
  .rank { color: #888; width: 2.5rem; }
  .name { color: #dbb154; }
  .name a { color: #dbb154; text-decoration: none; }
  .name a:hover { color: #f0c96c; text-decoration: underline; }
  .combo { color: #888; }
  .score { color: #6a6; text-align: right; }
  .xl { text-align: center; }
  .place { color: #888; }
  .win { color: #6a6; }
  .death { color: #d55; font-size: 13px; }
  .dur { color: #888; }
  .date { color: #888; font-size: 13px; white-space: nowrap; }
  .morgue { font-size: 12px; }
  .pct { text-align: right; }
  .num { text-align: right; }
  .god { color: #a7e; }
  .race { color: #5fd7ff; }
  .cls { color: white; }
  .version { color: #888; font-size: 12px; }
  td.zero { color: #444; }
  .records-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
  .record-card { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-left: 3px solid #5fd7ff; border-radius: 4px; padding: 0.8rem 1rem; }
  .record-card .record-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #888; margin-bottom: .4rem; }
  .record-card .record-value { font-size: 18px; color: white; margin-bottom: .2rem; }
  .record-card .record-detail { font-size: 13px; color: #888; line-height: 1.5; }
  .record-card .record-detail .name { color: #dbb154; }
  .section-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 2rem; }
  .section-grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0 2rem; }
  .back-link { font-size: 14px; color: #888; }
  .back-link:hover { color: white; }
  .footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #222; color: #555; font-size: 14px; }
  .footer a { color: #555; margin-right: 1.5rem; }
  .footer a:hover { color: #fff; }
  @media (max-width: 960px) { .section-grid-3 { grid-template-columns: 1fr 1fr; } }
  @media (max-width: 768px) { .section-grid, .section-grid-3 { grid-template-columns: 1fr; } .records-grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>

<div class="header">
Welcome to <b>__SERVER_ABBR__</b> (<a href="__SERVER_URL__">__SERVER_HOST__</a>) WebTiles!
<br>Please read and follow the <a href="/code_of_conduct.txt">Code of Conduct</a> for this server.
</div>

<div class="nav">
  <a href="/">&larr; Back to Lobby</a><span class="sep">|</span><a href="/scores/">Scores</a><span class="sep">|</span><a href="/stats" class="active">Stats</a><span class="sep">|</span><a href="/scores/players/" id="nav-profile">Profile</a><span class="sep">|</span><a href="/morgue/" id="nav-morgue">Morgue</a><span class="sep">|</span><a href="/ttyrec/" id="nav-ttyrec">Recordings</a><span class="sep">|</span><a href="/rcfiles/crawl-0.34/" id="nav-rcfiles">RC Files</a>
</div>
<script>!function(){var u=null;for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);if(k&&k.endsWith("_user")){u=localStorage.getItem(k);break}}if(u){var p=document.getElementById("nav-profile");if(p)p.href="/scores/players/"+u+".html";var m=document.getElementById("nav-morgue");if(m)m.href="/morgue/"+u+"/";var t=document.getElementById("nav-ttyrec");if(t)t.href="/ttyrec/"+u+"/";var r=document.getElementById("nav-rcfiles");if(r)r.href="/rcfiles/crawl-0.34/"+u+".rc";}}()</script>

<div class="section-nav">
  <a href="#records">Records</a><span class="sn-sep">&middot;</span><a href="#wins">Wins</a><span class="sn-sep">&middot;</span><a href="#deaths">Deaths</a><span class="sn-sep">&middot;</span><a href="#streaks">Streaks</a><span class="sn-sep">&middot;</span><a href="#speed">Speed</a><span class="sn-sep">&middot;</span><a href="#monsters">Monsters</a><span class="sn-sep">&middot;</span><a href="#players">Players</a><span class="sn-sep">&middot;</span><a href="#races">Races</a><span class="sn-sep">&middot;</span><a href="#classes">Classes</a><span class="sn-sep">&middot;</span><a href="#gods">Gods</a>
</div>

<h1>Server Statistics</h1>

<div class="stat-bar">
  <div class="stat">Players <span>{{ unique_players }}</span></div>
  <div class="stat">Games <span>{{ total_games }}</span></div>
  <div class="stat">Victories <span>{{ total_wins }}</span></div>
  <div class="stat">Win Rate <span>{% if total_games %}{{ "%.1f"|format(total_wins/total_games*100) }}%{% else %}&mdash;{% endif %}</span></div>
  <div class="stat">Updated <span>{{ updated }}</span></div>
</div>

<main>

  <!-- ── Server Records ──────────────────────────────────────── -->
  <h2 id="records">Server Records</h2>
  <div class="records-grid">
    {% if highest_score %}
    <div class="record-card">
      <div class="record-label">Highest Score</div>
      <div class="record-value">{{ highest_score.score_fmt }}</div>
      <div class="record-detail">
        <span class="name">{{ highest_score.name }}</span>
        &mdash; <span class="combo">{{ highest_score.combo }}</span>
        {% if highest_score.win %}<span class="win">(WON)</span>{% endif %}
        <br>{{ highest_score.date }}
      </div>
    </div>
    {% endif %}
    {% if fastest_win %}
    <div class="record-card">
      <div class="record-label">Fastest Win (Real Time)</div>
      <div class="record-value">{{ fastest_win.dur }}</div>
      <div class="record-detail">
        <span class="name">{{ fastest_win.name }}</span>
        &mdash; <span class="combo">{{ fastest_win.combo }}</span>
        <br>{{ fastest_win.turns }} turns &middot; {{ fastest_win.date }}
      </div>
    </div>
    {% endif %}
    {% if fewest_turns_win %}
    <div class="record-card">
      <div class="record-label">Fewest Turns Win</div>
      <div class="record-value">{{ fewest_turns_win.turns }} turns</div>
      <div class="record-detail">
        <span class="name">{{ fewest_turns_win.name }}</span>
        &mdash; <span class="combo">{{ fewest_turns_win.combo }}</span>
        <br>{{ fewest_turns_win.date }}
      </div>
    </div>
    {% endif %}
    {% if most_runes %}
    <div class="record-card">
      <div class="record-label">Most Runes</div>
      <div class="record-value">{{ most_runes.runes }} runes</div>
      <div class="record-detail">
        <span class="name">{{ most_runes.name }}</span>
        &mdash; <span class="combo">{{ most_runes.combo }}</span>
        {% if most_runes.win %}<span class="win">(WON)</span>{% endif %}
        <br>{{ most_runes.date }}
      </div>
    </div>
    {% endif %}
    {% if most_turns_win %}
    <div class="record-card">
      <div class="record-label">Longest Win (Turns)</div>
      <div class="record-value">{{ most_turns_win.turns }} turns</div>
      <div class="record-detail">
        <span class="name">{{ most_turns_win.name }}</span>
        &mdash; <span class="combo">{{ most_turns_win.combo }}</span>
        <br>{{ most_turns_win.date }}
      </div>
    </div>
    {% endif %}
  </div>

  <!-- ── Recent Wins ────────────────────────────────────────── -->
  <h2 id="wins">Recent Wins</h2>
  <table>
    <thead><tr>
      <th>Player</th><th>Combo</th><th>God</th><th>XL</th><th>Score</th><th>Runes</th><th>Time</th><th>Date</th><th></th>
    </tr></thead>
    <tbody>
    {% for g in recent_wins %}
    <tr>
      <td class="name"><a href="/scores/players/{{ g.name }}.html">{{ g.name }}</a></td>
      <td class="combo">{{ g.race }} {{ g.cls }}</td>
      <td class="god">{{ g.god }}</td>
      <td class="xl">{{ g.xl }}</td>
      <td class="score">{{ g.score_fmt }}</td>
      <td class="num">{{ g.runes }}</td>
      <td class="dur">{{ g.dur }}</td>
      <td class="date">{{ g.date }}</td>
      <td class="morgue">{% if g.morgue %}<a href="{{ g.morgue }}">morgue</a>{% endif %}</td>
    </tr>
    {% else %}
    <tr><td colspan="9" style="color:#666;padding:1rem">No victories yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <!-- ── Recent Notable Deaths ────────────────────────────── -->
  <h2 id="deaths">Recent Notable Deaths</h2>
  <table>
    <thead><tr>
      <th>Player</th><th>Combo</th><th>God</th><th>XL</th><th>Place</th><th>Cause</th><th>Date</th><th></th>
    </tr></thead>
    <tbody>
    {% for g in recent_deaths %}
    <tr>
      <td class="name"><a href="/scores/players/{{ g.name }}.html">{{ g.name }}</a></td>
      <td class="combo">{{ g.race }} {{ g.cls }}</td>
      <td class="god">{{ g.god }}</td>
      <td class="xl">{{ g.xl }}</td>
      <td class="place">{{ g.place }}</td>
      <td class="death">{{ g.killer }}</td>
      <td class="date">{{ g.date }}</td>
      <td class="morgue">{% if g.morgue %}<a href="{{ g.morgue }}">morgue</a>{% endif %}</td>
    </tr>
    {% else %}
    <tr><td colspan="8" style="color:#666;padding:1rem">No notable deaths recorded yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <!-- ── Win Streaks ────────────────────────────────────────── -->
  <h2 id="streaks">Win Streaks</h2>
  <table>
    <thead><tr>
      <th class="rank">#</th>
      <th>Player</th>
      <th>Length</th>
      <th>Games</th>
      <th>Start</th>
      <th>End</th>
      <th>Status</th>
    </tr></thead>
    <tbody>
    {% for s in streaks %}
    <tr>
      <td class="rank">{{ loop.index }}</td>
      <td class="name"><a href="/scores/players/{{ s.name }}.html">{{ s.name }}</a></td>
      <td class="num win">{{ s.length }}</td>
      <td class="combo">{{ s.games|join(", ") }}</td>
      <td class="date">{{ s.start }}</td>
      <td class="date">{{ s.end }}</td>
      <td class="{% if s.active %}win{% else %}dur{% endif %}">{% if s.active %}Active{% else %}Ended{% endif %}</td>
    </tr>
    {% else %}
    <tr><td colspan="7" style="color:#666;padding:1rem">No win streaks recorded yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <!-- ── Fastest Wins ────────────────────────────────────────── -->
  <div>
    <div>
      <h2 id="speed">Fastest Wins (Real Time)</h2>
      <table>
        <thead><tr>
          <th class="rank">#</th>
          <th>Player</th>
          <th>Combo</th>
          <th>God</th>
          <th>Time</th>
          <th>Score</th>
          <th>Runes</th>
          <th>Date</th>
          <th></th>
        </tr></thead>
        <tbody>
        {% for g in fastest_by_time %}
        <tr>
          <td class="rank">{{ loop.index }}</td>
          <td class="name"><a href="/scores/players/{{ g.name }}.html">{{ g.name }}</a></td>
          <td class="combo">{{ g.race }} {{ g.cls }}</td>
          <td class="god">{{ g.god }}</td>
          <td class="dur">{{ g.dur }}</td>
          <td class="score">{{ g.score_fmt }}</td>
          <td class="num">{{ g.runes }}</td>
          <td class="date">{{ g.date }}</td>
          <td class="morgue">{% if g.morgue %}<a href="{{ g.morgue }}">morgue</a>{% endif %}</td>
        </tr>
        {% else %}
        <tr><td colspan="9" style="color:#666;padding:1rem">No victories yet.</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    <div>
      <h2>Fastest Wins (Turn Count)</h2>
      <table>
        <thead><tr>
          <th class="rank">#</th>
          <th>Player</th>
          <th>Combo</th>
          <th>God</th>
          <th>Turns</th>
          <th>Score</th>
          <th>Runes</th>
          <th>Date</th>
          <th></th>
        </tr></thead>
        <tbody>
        {% for g in fastest_by_turns %}
        <tr>
          <td class="rank">{{ loop.index }}</td>
          <td class="name"><a href="/scores/players/{{ g.name }}.html">{{ g.name }}</a></td>
          <td class="combo">{{ g.race }} {{ g.cls }}</td>
          <td class="god">{{ g.god }}</td>
          <td class="num">{{ g.turns }}</td>
          <td class="score">{{ g.score_fmt }}</td>
          <td class="num">{{ g.runes }}</td>
          <td class="date">{{ g.date }}</td>
          <td class="morgue">{% if g.morgue %}<a href="{{ g.morgue }}">morgue</a>{% endif %}</td>
        </tr>
        {% else %}
        <tr><td colspan="9" style="color:#666;padding:1rem">No victories yet.</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <!-- ── Deadliest Monsters ──────────────────────────────────── -->
  <h2 id="monsters">Deadliest Monsters</h2>
  <table>
    <thead><tr>
      <th class="rank">#</th>
      <th>Monster</th>
      <th>Kills</th>
      <th>% of Deaths</th>
      <th>Last Victim</th>
      <th></th>
    </tr></thead>
    <tbody>
    {% for k in top_killers %}
    <tr>
      <td class="rank">{{ loop.index }}</td>
      <td class="death">{{ k.name }}</td>
      <td class="num">{{ k.count }}</td>
      <td class="pct">{{ k.pct }}%</td>
      <td class="name"><a href="/scores/players/{{ k.last_victim }}.html">{{ k.last_victim }}</a></td>
      <td class="morgue">{% if k.last_victim_morgue %}<a href="{{ k.last_victim_morgue }}">morgue</a>{% endif %}</td>
    </tr>
    {% else %}
    <tr><td colspan="6" style="color:#666;padding:1rem">No deaths recorded yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <!-- ── Player Stats ────────────────────────────────────────── -->
  <h2 id="players">Player Statistics</h2>
  <table>
    <thead><tr>
      <th class="rank">#</th>
      <th>Player</th>
      <th>Games</th>
      <th>Wins</th>
      <th>Win %</th>
      <th>Best Score</th>
      <th>Best XL</th>
      <th>Playtime</th>
    </tr></thead>
    <tbody>
    {% for p in players %}
    <tr>
      <td class="rank">{{ loop.index }}</td>
      <td class="name"><a href="/scores/players/{{ p.name }}.html">{{ p.name }}</a></td>
      <td class="num">{{ p.games }}</td>
      <td class="num{% if p.wins > 0 %} win{% else %} zero{% endif %}">{{ p.wins }}</td>
      <td class="pct">{{ p.win_rate }}%</td>
      <td class="score">{{ p.best_score_fmt }}</td>
      <td class="xl">{{ p.best_xl }}</td>
      <td class="dur">{{ p.playtime }}</td>
    </tr>
    {% else %}
    <tr><td colspan="8" style="color:#666;padding:1rem">No players yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <!-- ── Race / Class / God Stats ────────────────────────────── -->
  <div class="section-grid-3">

    <div>
      <h2 id="races">Win Rate by Race</h2>
      <table>
        <thead><tr>
          <th>Race</th><th>Games</th><th>Wins</th><th>Win %</th>
        </tr></thead>
        <tbody>
        {% for r in races %}
        <tr>
          <td class="race">{{ r.name }}</td>
          <td class="num">{{ r.games }}</td>
          <td class="num{% if r.wins > 0 %} win{% else %} zero{% endif %}">{{ r.wins }}</td>
          <td class="pct">{{ r.win_rate }}%</td>
        </tr>
        {% else %}
        <tr><td colspan="4" style="color:var(--muted)">No data.</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>

    <div>
      <h2 id="classes">Win Rate by Class</h2>
      <table>
        <thead><tr>
          <th>Class</th><th>Games</th><th>Wins</th><th>Win %</th>
        </tr></thead>
        <tbody>
        {% for c in classes %}
        <tr>
          <td class="cls">{{ c.name }}</td>
          <td class="num">{{ c.games }}</td>
          <td class="num{% if c.wins > 0 %} win{% else %} zero{% endif %}">{{ c.wins }}</td>
          <td class="pct">{{ c.win_rate }}%</td>
        </tr>
        {% else %}
        <tr><td colspan="4" style="color:var(--muted)">No data.</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>

    <div>
      <h2 id="gods">Win Rate by God</h2>
      <table>
        <thead><tr>
          <th>God</th><th>Games</th><th>Wins</th><th>Win %</th>
        </tr></thead>
        <tbody>
        {% for g in gods %}
        <tr>
          <td class="god">{{ g.name }}</td>
          <td class="num">{{ g.games }}</td>
          <td class="num{% if g.wins > 0 %} win{% else %} zero{% endif %}">{{ g.wins }}</td>
          <td class="pct">{{ g.win_rate }}%</td>
        </tr>
        {% else %}
        <tr><td colspan="4" style="color:var(--muted)">No data.</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>

  </div>

</main>

</body>
</html>
"""

STATS_TEMPLATE = Template(_apply_server_branding(STATS_HTML_TEMPLATE))


# ── Player profile HTML template ────────────────────────────────────────────

PLAYER_HTML_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ name }} — DCSS — __SERVER_ABBR__</title>
<link rel="icon" href="/static/stone_soup_icon-32x32.png" type="image/png">
<style>
  @media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
  body { background: black; color: white; font-family: DejaVu Sans Mono, monospace; font-size: 16px; line-height: 1.6; margin: 0; padding: 1.5rem 2rem; }
  a { color: white; text-decoration: underline; }
  a:hover { color: lightgrey; }
  .header { margin-bottom: 0.5rem; }
  .nav { margin-bottom: 1rem; color: #888; }
  .nav a { color: #888; margin-right: 0.5rem; }
  .nav a:hover { color: white; }
  .nav a.active { color: white; }
  .nav .sep { color: #444; margin-right: 0.5rem; }
  .section-nav { margin-bottom: 1rem; padding: 0.5rem 0; border-bottom: 1px solid #222; position: sticky; top: 0; background: black; z-index: 3; font-size: 13px; }
  .section-nav a { color: #888; text-decoration: none; margin-right: 0.3rem; }
  .section-nav a:hover { color: #5fd7ff; }
  .section-nav .sn-sep { color: #333; margin-right: 0.3rem; }
  h1 { font-size: 16px; font-weight: normal; margin: 0.5rem 0; }
  h2 { font-size: 16px; font-weight: normal; color: #5fd7ff; margin: 1.5rem 0 0.5rem; border-bottom: 1px solid #222; padding-bottom: 0.3rem; scroll-margin-top: 3rem; }
  main { max-width: 1200px; flex: 1; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 1rem; }
  thead th { color: #888; text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #333; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
  thead { position: sticky; top: 2rem; background: black; z-index: 2; }
  tbody tr:hover { background: rgba(255,255,255,0.06); }
  td { padding: .3rem .5rem; border-bottom: 1px solid #1a1a1a; }
  .rank { color: #888; width: 2.5rem; }
  .name { color: #dbb154; }
  .name a { color: #dbb154; text-decoration: none; }
  .name a:hover { color: #f0c96c; text-decoration: underline; }
  .combo { color: #888; }
  .score { color: #6a6; text-align: right; }
  .xl { text-align: center; }
  .place { color: #888; }
  .win { color: #6a6; }
  .death { color: #d55; font-size: 13px; }
  .dur { color: #888; }
  .date { color: #888; font-size: 13px; white-space: nowrap; }
  .morgue { font-size: 12px; }
  .pct { text-align: right; }
  .num { text-align: right; }
  .god { color: #a7e; }
  .race { color: #5fd7ff; }
  .cls { color: white; }
  .version { color: #888; font-size: 12px; }
  td.zero { color: #444; }
  .records-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
  .record-card { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-left: 3px solid #5fd7ff; border-radius: 4px; padding: 0.8rem 1rem; }
  .record-card .record-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #888; margin-bottom: .4rem; }
  .record-card .record-value { font-size: 18px; color: white; margin-bottom: .2rem; }
  .record-card .record-detail { font-size: 13px; color: #888; line-height: 1.5; }
  .footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #222; color: #555; font-size: 14px; }
  .footer a { color: #555; margin-right: 1.5rem; }
  .footer a:hover { color: #fff; }
  @media (max-width: 768px) { .records-grid { grid-template-columns: 1fr 1fr; } }
</style>
</head>
<body>

<div class="header">
Welcome to <b>__SERVER_ABBR__</b> (<a href="__SERVER_URL__">__SERVER_HOST__</a>) WebTiles!
<br>Please read and follow the <a href="/code_of_conduct.txt">Code of Conduct</a> for this server.
</div>

<div class="nav">
  <a href="/">&larr; Back to Lobby</a><span class="sep">|</span><a href="/scores/">Scores</a><span class="sep">|</span><a href="/stats">Stats</a><span class="sep">|</span><a href="/scores/players/{{ name }}.html" class="active">Profile</a><span class="sep">|</span><a href="/morgue/{{ name }}/">Morgue</a><span class="sep">|</span><a href="/ttyrec/{{ name }}/">Recordings</a><span class="sep">|</span><a href="/rcfiles/crawl-0.34/" id="nav-rcfiles">RC Files</a>
</div>

<h1><span class="name">{{ name }}</span></h1>

<main>

  <!-- ── Summary ────────────────────────────────────────────── -->
  <h2>Summary</h2>
  <div class="records-grid">
    <div class="record-card">
      <div class="record-label">Games Played</div>
      <div class="record-value">{{ games_played }}</div>
    </div>
    <div class="record-card">
      <div class="record-label">Wins</div>
      <div class="record-value">{{ wins }}{% if games_played %} <span style="font-size:13px;color:#888">({{ win_pct }}%)</span>{% endif %}</div>
    </div>
    <div class="record-card">
      <div class="record-label">Best Score</div>
      <div class="record-value">{{ best_score_fmt }}</div>
    </div>
    <div class="record-card">
      <div class="record-label">Best XL</div>
      <div class="record-value">{{ best_xl }}</div>
    </div>
    <div class="record-card">
      <div class="record-label">Favorite Race</div>
      <div class="record-value"><span class="race">{{ fav_race }}</span></div>
    </div>
    <div class="record-card">
      <div class="record-label">Favorite Class</div>
      <div class="record-value"><span class="cls">{{ fav_class }}</span></div>
    </div>
    <div class="record-card">
      <div class="record-label">Favorite God</div>
      <div class="record-value"><span class="god">{{ fav_god }}</span></div>
    </div>
    <div class="record-card">
      <div class="record-label">Playtime</div>
      <div class="record-value">{{ playtime }}</div>
    </div>
  </div>

  {% if win_history %}
  <!-- ── Win History ────────────────────────────────────────── -->
  <h2>Win History ({{ wins }} total)</h2>
  <table>
    <thead><tr>
      <th class="rank">#</th>
      <th>Combo</th>
      <th>God</th>
      <th>XL</th>
      <th>Score</th>
      <th>Runes</th>
      <th>Time</th>
      <th>Turns</th>
      <th>Date</th>
      <th></th>
    </tr></thead>
    <tbody>
    {% for g in win_history %}
    <tr>
      <td class="rank">{{ loop.index }}</td>
      <td class="combo">{{ g.race }} {{ g.cls }}</td>
      <td class="god">{{ g.god }}</td>
      <td class="xl">{{ g.xl }}</td>
      <td class="score">{{ g.score_fmt }}</td>
      <td class="num">{{ g.runes }}</td>
      <td class="dur">{{ g.dur }}</td>
      <td class="num">{{ g.turns }}</td>
      <td class="date">{{ g.date }}</td>
      <td class="morgue">{% if g.morgue %}<a href="{{ g.morgue }}">morgue</a>{% endif %}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% endif %}

  <!-- ── Recent Games ──────────────────────────────────────── -->
  <h2>Recent Games</h2>
  <table>
    <thead><tr>
      <th class="rank">#</th>
      <th>Combo</th>
      <th>God</th>
      <th>XL</th>
      <th>Score</th>
      <th>Place</th>
      <th>Outcome</th>
      <th>Date</th>
      <th></th>
    </tr></thead>
    <tbody>
    {% for g in recent_games %}
    <tr>
      <td class="rank">{{ loop.index }}</td>
      <td class="combo">{{ g.race }} {{ g.cls }}</td>
      <td class="god">{{ g.god }}</td>
      <td class="xl">{{ g.xl }}</td>
      <td class="score">{{ g.score_fmt }}</td>
      <td class="place">{{ g.place }}</td>
      <td class="{{ g.outcome_cls }}">{{ g.outcome_str }}</td>
      <td class="date">{{ g.date }}</td>
      <td class="morgue">{% if g.morgue %}<a href="{{ g.morgue }}">morgue</a>{% endif %}</td>
    </tr>
    {% else %}
    <tr><td colspan="9" style="color:#666;padding:1rem">No games recorded.</td></tr>
    {% endfor %}
    </tbody>
  </table>

</main>

</body>
</html>
"""

PLAYER_TEMPLATE = Template(_apply_server_branding(PLAYER_HTML_TEMPLATE))


def write_player_pages(all_games: list[dict]):
    """Generate individual HTML profile pages for each player."""
    players_dir = os.path.join(OUTPUT_DIR, "players")
    os.makedirs(players_dir, exist_ok=True)

    # Group games by player
    by_player: dict[str, list[dict]] = defaultdict(list)
    for g in all_games:
        name = g.get("name", "")
        if name:
            by_player[name].append(g)

    written = 0
    for name, games in by_player.items():
        games_sorted = sorted(games, key=lambda g: g.get("end", ""), reverse=True)

        # Summary stats
        wins_count = sum(1 for g in games if is_win(g))
        best_sc = max((score(g) for g in games), default=0)
        best_xl = max((int(g.get("xl", 0) or 0) for g in games), default=0)
        total_dur = sum(int(g.get("dur", 0) or 0) for g in games)

        races: dict[str, int] = defaultdict(int)
        classes: dict[str, int] = defaultdict(int)
        gods: dict[str, int] = defaultdict(int)
        for g in games:
            r = g.get("race", "")
            c = g.get("cls", "")
            god = g.get("god", "")
            if r:
                races[r] += 1
            if c:
                classes[c] += 1
            if god:
                gods[god] += 1

        fav_race = max(races, key=races.get) if races else "-"
        fav_class = max(classes, key=classes.get) if classes else "-"
        fav_god = max(gods, key=gods.get) if gods else "-"
        win_pct = f"{wins_count / len(games) * 100:.1f}" if games else "0.0"

        # Win history (all wins, most recent first)
        win_history = []
        for g in games_sorted:
            if is_win(g):
                win_history.append({
                    "race": g.get("race", "?"),
                    "cls": g.get("cls", "?"),
                    "god": g.get("god", "-"),
                    "xl": g.get("xl", "?"),
                    "score_fmt": fmt_score(score(g)),
                    "runes": g.get("urune", "0"),
                    "dur": fmt_dur(g.get("dur", "0")),
                    "turns": f"{int(g.get('turn', 0) or 0):,}",
                    "date": fmt_date(g.get("end", "")),
                    "morgue": morgue_link(g),
                })

        # Recent games (last 20)
        recent_games = []
        for g in games_sorted[:20]:
            recent_games.append({
                "race": g.get("race", "?"),
                "cls": g.get("cls", "?"),
                "god": g.get("god", "-"),
                "xl": g.get("xl", "?"),
                "score_fmt": fmt_score(score(g)),
                "place": g.get("place", "?").replace("::", ":"),
                "outcome_str": outcome(g),
                "outcome_cls": outcome_class(g),
                "date": fmt_date(g.get("end", "")),
                "morgue": morgue_link(g),
            })

        ctx = {
            "name": name,
            "games_played": len(games),
            "wins": wins_count,
            "win_pct": win_pct,
            "best_score_fmt": fmt_score(best_sc),
            "best_xl": best_xl,
            "fav_race": fav_race,
            "fav_class": fav_class,
            "fav_god": fav_god,
            "playtime": fmt_dur(str(total_dur)),
            "win_history": win_history,
            "recent_games": recent_games,
        }

        html = PLAYER_TEMPLATE.render(**ctx)
        out = os.path.join(players_dir, f"{name}.html")
        tmp = out + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(html)
        os.replace(tmp, out)
        written += 1

    print(f"  Player pages: {written} HTML profiles written")


def write_stats_page(all_games: list[dict]):
    """Generate stats.html with detailed server statistics."""
    stats = build_detailed_stats(all_games)
    stats["update_interval"] = UPDATE_INTERVAL

    html = STATS_TEMPLATE.render(**stats)
    out = os.path.join(OUTPUT_DIR, "stats.html")
    tmp = out + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(html)
    os.replace(tmp, out)


# ── HTML template ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{{ update_interval }}">
<title>Leaderboard — DCSS — __SERVER_ABBR__</title>
<link rel="icon" href="/static/stone_soup_icon-32x32.png" type="image/png">
<style>
  @media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
  body { background: black; color: white; font-family: DejaVu Sans Mono, monospace; font-size: 16px; line-height: 1.6; margin: 0; padding: 1.5rem 2rem; }
  a { color: white; text-decoration: underline; }
  a:hover { color: lightgrey; }
  .header { margin-bottom: 0.5rem; }
  .nav { margin-bottom: 1rem; color: #888; }
  .nav a { color: #888; margin-right: 0.5rem; }
  .nav a:hover { color: white; }
  .nav a.active { color: white; }
  .nav .sep { color: #444; margin-right: 0.5rem; }
  .section-nav { margin-bottom: 1rem; padding: 0.5rem 0; border-bottom: 1px solid #222; position: sticky; top: 0; background: black; z-index: 3; font-size: 13px; }
  .section-nav a { color: #888; text-decoration: none; margin-right: 0.3rem; }
  .section-nav a:hover { color: #5fd7ff; }
  .section-nav .sn-sep { color: #333; margin-right: 0.3rem; }
  h1 { font-size: 16px; font-weight: normal; margin: 0.5rem 0; }
  h2 { font-size: 16px; font-weight: normal; color: #5fd7ff; margin: 1.5rem 0 0.5rem; border-bottom: 1px solid #222; padding-bottom: 0.3rem; scroll-margin-top: 3rem; }
  .stat-bar { margin-bottom: 1rem; color: #888; }
  .stat-bar span { color: white; }
  main { max-width: 1100px; flex: 1; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 1rem; }
  thead th { color: #888; text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #333; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
  thead { position: sticky; top: 2rem; background: black; z-index: 2; }
  tbody tr:hover { background: rgba(255,255,255,0.06); }
  td { padding: .3rem .5rem; border-bottom: 1px solid #1a1a1a; }
  .rank { color: #888; width: 2.5rem; }
  .name { color: #dbb154; }
  .name a { color: #dbb154; text-decoration: none; }
  .name a:hover { color: #f0c96c; text-decoration: underline; }
  .combo { color: #888; }
  .score { color: #6a6; text-align: right; }
  .xl { text-align: center; }
  .place { color: #888; }
  .win { color: #6a6; }
  .death { color: #d55; font-size: 13px; }
  .dur { color: #888; }
  .date { color: #888; font-size: 13px; white-space: nowrap; }
  .morgue { font-size: 12px; }
  .milestone { color: #a7e; font-size: 13px; }
  .section-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 2rem; }
  .footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #222; color: #555; font-size: 14px; }
  .footer a { color: #555; margin-right: 1.5rem; }
  .footer a:hover { color: #fff; }
  @media (max-width: 768px) { .section-grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>

<div class="header">
Welcome to <b>__SERVER_ABBR__</b> (<a href="__SERVER_URL__">__SERVER_HOST__</a>) WebTiles!
<br>Please read and follow the <a href="/code_of_conduct.txt">Code of Conduct</a> for this server.
</div>

<div class="nav">
  <a href="/">&larr; Back to Lobby</a><span class="sep">|</span><a href="/scores/" class="active">Scores</a><span class="sep">|</span><a href="/stats">Stats</a><span class="sep">|</span><a href="/scores/players/" id="nav-profile">Profile</a><span class="sep">|</span><a href="/morgue/" id="nav-morgue">Morgue</a><span class="sep">|</span><a href="/ttyrec/" id="nav-ttyrec">Recordings</a><span class="sep">|</span><a href="/rcfiles/crawl-0.34/" id="nav-rcfiles">RC Files</a>
</div>
<script>!function(){var u=null;for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);if(k&&k.endsWith("_user")){u=localStorage.getItem(k);break}}if(u){var p=document.getElementById("nav-profile");if(p)p.href="/scores/players/"+u+".html";var m=document.getElementById("nav-morgue");if(m)m.href="/morgue/"+u+"/";var t=document.getElementById("nav-ttyrec");if(t)t.href="/ttyrec/"+u+"/";var r=document.getElementById("nav-rcfiles");if(r)r.href="/rcfiles/crawl-0.34/"+u+".rc";}}()</script>

<div class="section-nav">
  <a href="#top">Top Scores</a><span class="sn-sep">&middot;</span><a href="#victories">Victories</a><span class="sn-sep">&middot;</span><a href="#recent">Recent Games</a><span class="sn-sep">&middot;</span><a href="#milestones">Milestones</a><span class="sn-sep">&middot;</span><a href="#players">Players</a>
</div>

<h1>Hall of Heroes</h1>

<div class="stat-bar">
  Games <span>{{ total_games }}</span> &middot;
  Victories <span>{{ total_wins }}</span> &middot;
  Win Rate <span>{% if total_games %}{{ "%.1f"|format(total_wins/total_games*100) }}%{% else %}&mdash;{% endif %}</span>
  <div class="stat">Updated <span>{{ updated }}</span></div>
</div>

<main>

  <h2 id="top">Top Scores All-Time</h2>
  <table>
    <thead><tr>
      <th class="rank">#</th>
      <th>Player</th>
      <th>Combo</th>
      <th>XL</th>
      <th>Score</th>
      <th>Place</th>
      <th>Outcome</th>
      <th>Date</th>
      <th></th>
    </tr></thead>
    <tbody>
    {% for g in top_scores %}
    <tr>
      <td class="rank">{{ loop.index }}</td>
      <td class="name"><a href="/scores/players/{{ g.get('name','?') }}.html">{{ g.get("name","?") }}</a></td>
      <td class="combo">{{ g.get("race","?") }} {{ g.get("cls","?") }}</td>
      <td class="xl">{{ g.get("xl","?") }}</td>
      <td class="score">{{ g.sc_fmt }}</td>
      <td class="place">{{ g.get("place","?") }}</td>
      <td class="{{ g.outcome_cls }}">{{ g.outcome_str }}</td>
      <td class="date">{{ g.date_fmt }}</td>
      <td class="morgue">{% if g.mlink %}<a href="{{ g.mlink }}">morgue</a>{% endif %}</td>
    </tr>
    {% else %}
    <tr><td colspan="9" style="color:var(--dim);padding:1rem">No games recorded yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <h2 id="victories">Recent Victories</h2>
  <table>
    <thead><tr>
      <th>Player</th><th>Combo</th><th>XL</th><th>Score</th><th>Turns</th><th>Date</th>
    </tr></thead>
    <tbody>
    {% for g in recent_wins %}
    <tr>
      <td class="name"><a href="/scores/players/{{ g.get('name','?') }}.html">{{ g.get("name","?") }}</a></td>
      <td class="combo">{{ g.get("race","?") }} {{ g.get("cls","?") }}</td>
      <td class="xl">{{ g.get("xl","?") }}</td>
      <td class="score">{{ g.sc_fmt }}</td>
      <td class="dur">{{ g.get("turn","?") }}</td>
      <td class="date">{{ g.date_fmt }}</td>
    </tr>
    {% else %}
    <tr><td colspan="6" style="color:#666">No victories yet — the Orb awaits its first champion.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <h2 id="recent">Recent Games</h2>
  <table>
    <thead><tr>
      <th>Player</th><th>Combo</th><th>XL</th><th>Outcome</th><th>Date</th>
    </tr></thead>
    <tbody>
    {% for g in recent_games %}
    <tr>
      <td class="name"><a href="/scores/players/{{ g.get('name','?') }}.html">{{ g.get("name","?") }}</a></td>
      <td class="combo">{{ g.get("race","?") }} {{ g.get("cls","?") }}</td>
      <td class="xl">{{ g.get("xl","?") }}</td>
      <td class="{{ g.outcome_cls }}">{{ g.outcome_str[:40] }}</td>
      <td class="date">{{ g.date_fmt }}</td>
    </tr>
    {% else %}
    <tr><td colspan="5" style="color:#666">No games recorded yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <h2 id="milestones">Recent Milestones</h2>
  <table>
    <thead><tr>
      <th>Player</th><th>Combo</th><th>XL</th><th>Milestone</th><th>Place</th><th>When</th>
    </tr></thead>
    <tbody>
    {% for m in recent_milestones %}
    <tr>
      <td class="name"><a href="/scores/players/{{ m.name }}.html">{{ m.name }}</a></td>
      <td class="combo">{{ m.combo }}</td>
      <td class="xl">{{ m.xl }}</td>
      <td class="milestone">{{ m.milestone }}</td>
      <td class="place">{{ m.place }}</td>
      <td class="date">{{ m.time_ago }}</td>
    </tr>
    {% else %}
    <tr><td colspan="6" style="color:var(--dim)">No milestones recorded yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <h2 id="players">Player Statistics</h2>
  <table>
    <thead><tr>
      <th>Player</th><th>Games</th><th>Wins</th><th>Win %</th>
      <th>Best Score</th><th>Best XL</th>
    </tr></thead>
    <tbody>
    {% for p in players %}
    <tr>
      <td class="name"><a href="/scores/players/{{ p.name }}.html">{{ p.name }}</a></td>
      <td>{{ p.games }}</td>
      <td class="win">{{ p.wins }}</td>
      <td>{% if p.games %}{{ "%.1f"|format(p.wins/p.games*100) }}%{% else %}—{% endif %}</td>
      <td class="score">{{ "{:,}".format(p.best) }}</td>
      <td class="xl">{{ p.best_xl }}</td>
    </tr>
    {% else %}
    <tr><td colspan="6" style="color:var(--dim)">No players yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

</main>

</body>
</html>
"""

TEMPLATE = Template(_apply_server_branding(HTML_TEMPLATE))


def enrich(games: list[dict]) -> list[dict]:
    """Add pre-computed display fields to each game dict."""
    for g in games:
        g["sc_fmt"]      = fmt_score(score(g))
        g["date_fmt"]    = fmt_date(g.get("end", ""))
        g["dur_fmt"]     = fmt_dur(g.get("dur", "0"))
        g["outcome_str"] = outcome(g)
        g["outcome_cls"] = outcome_class(g)
        g["mlink"]       = morgue_link(g)
        place = g.get("place", "")
        if place:
            g["place"] = place.replace("::", ":")
    return games


def write_player_stats(all_games: list[dict]) -> None:
    """Write per-player JSON stat files for hub profile integration."""
    players_dir = os.path.join(OUTPUT_DIR, "players")
    os.makedirs(players_dir, exist_ok=True)

    # Group games by player name (case-insensitive key, preserve original)
    by_player: dict[str, list[dict]] = defaultdict(list)
    for g in all_games:
        name = g.get("name", "")
        if name:
            by_player[name].append(g)

    written = 0
    for name, games in by_player.items():
        wins = sum(1 for g in games if is_win(g))
        best_score = max((score(g) for g in games), default=0)
        best_xl = max((int(g.get("xl", 0) or 0) for g in games), default=0)
        total_dur = sum(int(g.get("dur", 0) or 0) for g in games)

        # Favorite race/class/god by frequency
        races: dict[str, int] = defaultdict(int)
        classes: dict[str, int] = defaultdict(int)
        gods: dict[str, int] = defaultdict(int)
        for g in games:
            r = g.get("race", "")
            c = g.get("cls", "")
            god = g.get("god", "")
            if r:
                races[r] += 1
            if c:
                classes[c] += 1
            if god:
                gods[god] += 1

        fav_race = max(races, key=races.get) if races else ""
        fav_class = max(classes, key=classes.get) if classes else ""
        fav_god = max(gods, key=gods.get) if gods else ""

        # Rune and combo stats for Discord role assignment
        max_runes = max((int(g.get("urune", 0) or 0) for g in games), default=0)
        winning_games = [g for g in games if is_win(g)]
        winning_combos = set()
        winning_races = set()
        winning_classes = set()
        winning_gods = set()
        has_15_rune_win = False
        for g in winning_games:
            r = g.get("race", "")
            c = g.get("cls", "")
            god = g.get("god", "")
            if r and c:
                winning_combos.add(f"{r}{c}")
            if r:
                winning_races.add(r)
            if c:
                winning_classes.add(c)
            if god:
                winning_gods.add(god)
            if int(g.get("urune", 0) or 0) >= 15:
                has_15_rune_win = True

        # Sort by end timestamp descending for recent games
        sorted_games = sorted(games, key=lambda g: g.get("end", ""), reverse=True)
        recent = []
        for g in sorted_games[:10]:
            recent.append({
                "race": g.get("race", ""),
                "cls": g.get("cls", ""),
                "xl": int(g.get("xl", 0) or 0),
                "score": score(g),
                "place": g.get("place", "").replace("::", ":"),
                "god": g.get("god", ""),
                "outcome": outcome(g),
                "date": fmt_date(g.get("end", "")),
                "version": g.get("v", g.get("_version", "")),
                "win": is_win(g),
            })

        player_data = {
            "username": name,
            "gamesPlayed": len(games),
            "wins": wins,
            "bestScore": best_score,
            "bestXL": best_xl,
            "favoriteRace": fav_race,
            "favoriteClass": fav_class,
            "favoriteGod": fav_god,
            "playtime": fmt_dur(str(total_dur)),
            "maxRunes": max_runes,
            "has15RuneWin": has_15_rune_win,
            "uniqueCombosWon": len(winning_combos),
            "distinctRacesWon": len(winning_races),
            "distinctClassesWon": len(winning_classes),
            "distinctGodsWon": len(winning_gods),
            # Lists exposed for cross-server role merging (set-union by Discord bot)
            "winningCombos": sorted(winning_combos),
            "winningRaces": sorted(winning_races),
            "winningClasses": sorted(winning_classes),
            "winningGods": sorted(winning_gods),
            "recentGames": recent,
        }

        # Write atomically using lowercase filename
        fname = os.path.join(players_dir, f"{name.lower()}.json")
        tmp = fname + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(player_data, fh, separators=(",", ":"))
        os.replace(tmp, fname)
        written += 1

    print(f"  Player stats: {written} player files written")


def generate():
    all_games = load_all_games()
    enrich(all_games)
    stats = build_stats(all_games)
    stats["update_interval"] = UPDATE_INTERVAL
    stats["recent_milestones"] = build_recent_milestones(load_all_milestones())

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html = TEMPLATE.render(**stats)
    out  = os.path.join(OUTPUT_DIR, "index.html")
    tmp  = out + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(html)
    os.replace(tmp, out)  # atomic replace

    # Generate banner stats JSON + stats page + per-player JSON + player HTML profiles from the same combined game list
    try:
        write_banner_stats(all_games)
        write_stats_page(all_games)
        write_player_stats(all_games)
        write_player_pages(all_games)
    except Exception as exc:
        print(f"[WARN] Banner/stats/player generation failed: {exc}")

    print(f"[{datetime.datetime.now():%H:%M:%S}] Scores updated — "
          f"{stats['total_games']} games, {stats['total_wins']} wins")


def main():
    print(f"DCSS scoring daemon started — polling every {UPDATE_INTERVAL}s")
    print(f"  Logfile : {LOGFILE}")
    print(f"  Output  : {OUTPUT_DIR}")
    while True:
        try:
            generate()
        except Exception as exc:
            print(f"[ERROR] {exc}")
        time.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    main()
