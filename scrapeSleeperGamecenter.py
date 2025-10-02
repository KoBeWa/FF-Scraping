# scrapeSleeperGamecenter.py
import os, json, csv, time
from collections import defaultdict
from pathlib import Path
import requests

BASE = "https://api.sleeper.app/v1"
OUT_DIR = Path("./output")
DATA_DIR = Path("./data")

LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID", "").strip()
SEASON = int(os.getenv("SEASON", "2022"))

# -------------------------- API WRAPPER -------------------------- #
def _get(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def get_league(league_id):           return _get(f"{BASE}/league/{league_id}")
def get_league_users(league_id):     return _get(f"{BASE}/league/{league_id}/users")
def get_league_rosters(league_id):   return _get(f"{BASE}/league/{league_id}/rosters")
def get_matchups(league_id, week):   return _get(f"{BASE}/league/{league_id}/matchups/{week}")
def get_players_cached():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / "sleeper_players.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 7*24*3600:
        return json.loads(cache.read_text(encoding="utf-8"))
    players = _get(f"{BASE}/players/nfl")  # große JSON
    cache.write_text(json.dumps(players), encoding="utf-8")
    return players

# -------------------------- HELPERS -------------------------- #
def short_name(player):
    if not player:
        return ""
    first = player.get("first_name") or ""
    last  = player.get("last_name") or (player.get("full_name") or "").split(" ")[-1]
    first_initial = (first[:1] + ". ") if first else ""
    return f"{first_initial}{last}".strip()

def fmt_player(players_db, pid):
    if not pid:
        return ""
    p = players_db.get(pid) or {}
    pos = p.get("position") or ""
    team = p.get("team") or p.get("metadata", {}).get("team_abbr") or ""
    if pos == "DEF":
        nick = p.get("full_name") or p.get("last_name") or team or "DEF"
        return f"{nick} DEF"
    name = short_name(p) if (p.get("first_name") or p.get("last_name")) else (p.get("full_name") or pid)
    suffix_team = f" - {team}" if team else ""
    return f"{name} {pos}{suffix_team}".strip()

def points_for(mapping, pid):
    try:
        return float(mapping.get(pid, 0.0))
    except Exception:
        return 0.0

def owner_maps(users, rosters):
    rid_to_owner = {r["roster_id"]: r.get("owner_id") for r in rosters}
    owner_to_name = {}
    for u in users:
        team_name = (u.get("metadata", {}) or {}).get("team_name")
        display = u.get("display_name") or "Unknown"
        owner_to_name[u["user_id"]] = team_name or display
    return rid_to_owner, owner_to_name

# --------------------- SLOT MAPPING (Classic) --------------------- #
PRIMARY_ORDER = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
BENCH_SLOTS = 7

def assign_starters_to_slots(players_db, starters, starters_points):
    qb = []; rb = []; wr = []; te = []; k = []; dst = []; flex_pool = []
    used = set()

    for pid in starters:
        pos = (players_db.get(pid, {}) or {}).get("position")
        if pos == "QB": qb.append(pid)
        elif pos == "RB": rb.append(pid); flex_pool.append(pid)
        elif pos == "WR": wr.append(pid); flex_pool.append(pid)
        elif pos == "TE": te.append(pid); flex_pool.append(pid)
        elif pos == "K": k.append(pid)
        elif pos == "DEF": dst.append(pid)
        else:
            pass

    keypts = lambda pid: -points_for(starters_points, pid)
    for lst in (qb, rb, wr, te, k, dst, flex_pool):
        lst.sort(key=keypts)

    slots = {"QB": None, "RB": [None, None], "WR": [None, None], "TE": None, "FLEX": None, "K": None, "DEF": None}
    slots["QB"] = qb[0] if qb else None
    slots["RB"][0] = rb[0] if len(rb) > 0 else None
    slots["RB"][1] = rb[1] if len(rb) > 1 else None
    slots["WR"][0] = wr[0] if len(wr) > 0 else None
    slots["WR"][1] = wr[1] if len(wr) > 1 else None
    slots["TE"] = te[0] if te else None
    slots["K"] = k[0] if k else None
    slots["DEF"] = dst[0] if dst else None

    for x in [slots["QB"], slots["TE"], slots["K"], slots["DEF"]]:
        if x: used.add(x)
    for x in slots["RB"] + slots["WR"]:
        if x: used.add(x)

    for pid in flex_pool:
        if pid not in used:
            slots["FLEX"] = pid
            break

    return slots

def bench_list(all_players, starters):
    starters_set = set(starters)
    return [pid for pid in all_players if pid not in starters_set]

# ----------------------------- MAIN ----------------------------- #
def main():
    if not LEAGUE_ID:
        raise SystemExit("Bitte SLEEPER_LEAGUE_ID als Umgebungsvariable setzen.")

    league = get_league(LEAGUE_ID)
    users = get_league_users(LEAGUE_ID)
    rosters = get_league_rosters(LEAGUE_ID)
    players_db = get_players_cached()
    rid_to_owner, owner_to_name = owner_maps(users, rosters)

    season_dir = OUT_DIR / str(SEASON)
    season_dir.mkdir(parents=True, exist_ok=True)

    # Wochenlogik: gehe weiter bis 2 leere Wochen in Folge (Cap 18)
    week = 1
    empty_streak = 0
    MAX_WEEK = 18

    while week <= MAX_WEEK and empty_streak < 2:
        week_data = get_matchups(LEAGUE_ID, week)
        if not week_data:
            empty_streak += 1
            week += 1
            continue
        empty_streak = 0

        # Gruppieren nach matchup_id
        by_mid = defaultdict(list)
        for t in week_data:
            by_mid[t.get("matchup_id")].append(t)

        rows = []
        totals = []
        team_total_by_roster = {}
        team_owner_by_roster = {}

        for teams in by_mid.values():
            for entry in teams:
                roster_id = entry["roster_id"]
                owner_id = rid_to_owner.get(roster_id)
                owner = owner_to_name.get(owner_id, f"Roster {roster_id}")

                starters = entry.get("starters") or []
                players_all = entry.get("players") or []
                players_points = entry.get("players_points") or {}
                starters_points = entry.get("starters_points") or {}

                if not starters_points and players_points and starters:
                    starters_points = {pid: players_points.get(pid, 0.0) for pid in starters}

                slots = assign_starters_to_slots(players_db, starters, starters_points)

                def p(pid): return round(points_for(players_points, pid), 2) if pid else ""

                bench = bench_list(players_all, starters)
                bench.sort(key=lambda pid: -points_for(players_points, pid))
                bench = bench[:BENCH_SLOTS]
                bench_pairs = []
                for i in range(BENCH_SLOTS):
                    pid = bench[i] if i < len(bench) else None
                    bench_pairs.append((fmt_player(players_db, pid), p(pid)))

                total = float(entry.get("points", sum(points_for(players_points, pid) for pid in starters)))
                total = round(total, 2)

                team_total_by_roster[roster_id] = total
                team_owner_by_roster[roster_id] = owner

                row = [
                    owner,  # Owner
                    "",     # Rank
                    fmt_player(players_db, slots["QB"]), p(slots["QB"]),
                    fmt_player(players_db, slots["RB"][0]), p(slots["RB"][0]),
                    fmt_player(players_db, slots["RB"][1]), p(slots["RB"][1]),
                    fmt_player(players_db, slots["WR"][0]), p(slots["WR"][0]),
                    fmt_player(players_db, slots["WR"][1]), p(slots["WR"][1]),
                    fmt_player(players_db, slots["TE"]), p(slots["TE"]),
                    fmt_player(players_db, slots["FLEX"]), p(slots["FLEX"]),
                    fmt_player(players_db, slots["K"]), p(slots["K"]),
                    fmt_player(players_db, slots["DEF"]), p(slots["DEF"]),
                ]
                for name, pts in bench_pairs:
                    row.extend([name, pts])
                row.extend([total, "", ""])

                rows.append({"roster_id": roster_id, "matchup_id": entry.get("matchup_id"), "row": row, "total": total})
                totals.append(total)

        # Rank (1 = beste Total)
        sorted_totals = sorted(set(totals), reverse=True)
        total_to_rank = {t: (i + 1) for i, t in enumerate(sorted_totals)}

        for pack in rows:
            rid = pack["roster_id"]
            mid = pack["matchup_id"]
            row = pack["row"]
            total = pack["total"]

            row[1] = total_to_rank.get(total, "")

            opponents = [x for x in rows if x["matchup_id"] == mid and x["roster_id"] != rid]
            if opponents:
                opp = opponents[0]
                opp_owner = team_owner_by_roster.get(opp["roster_id"], "")
                opp_total = team_total_by_roster.get(opp["roster_id"], "")
            else:
                opp_owner = "—"
                opp_total = ""

            row[-2] = opp_owner
            row[-1] = opp_total

        header = [
            "Owner","Rank",
            "QB","Points","RB","Points","RB","Points","WR","Points","WR","Points","TE","Points",
            "W/R","Points","K","Points","DEF","Points",
            "BN","Points","BN","Points","BN","Points","BN","Points","BN","Points","BN","Points","BN","Points",
            "Total","Opponent","Opponent Total"
        ]
        out_path = season_dir / f"gamecenter_week_{week}.csv"
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            for pack in rows:
                w.writerow(pack["row"])
        print(f"✓ Geschrieben: {out_path}")

        week += 1

if __name__ == "__main__":
    main()
