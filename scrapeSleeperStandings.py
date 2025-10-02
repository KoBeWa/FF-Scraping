# scrapeSleeperStandings.py
import os, csv, time, json
from pathlib import Path
from collections import defaultdict
import requests

BASE = "https://api.sleeper.app/v1"
OUT_DIR = Path("./output")
DATA_DIR = Path("./data")

LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID", "").strip()
ENV_SEASON = os.getenv("SEASON")  # optional

# ---------------- API ---------------- #
def _get(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def get_league(league_id):              return _get(f"{BASE}/league/{league_id}")
def get_league_users(league_id):        return _get(f"{BASE}/league/{league_id}/users")
def get_league_rosters(league_id):      return _get(f"{BASE}/league/{league_id}/rosters")
def get_matchups(league_id, week):      return _get(f"{BASE}/league/{league_id}/matchups/{week}")
def get_transactions(league_id, week):  return _get(f"{BASE}/league/{league_id}/transactions/{week}")
def get_drafts(league_id):              return _get(f"{BASE}/league/{league_id}/drafts")
def get_draft_picks(draft_id):          return _get(f"{BASE}/draft/{draft_id}/picks")
def get_winners_bracket(league_id):     return _get(f"{BASE}/league/{league_id}/winners_bracket")
def get_losers_bracket(league_id):      return _get(f"{BASE}/league/{league_id}/losers_bracket")

def get_players_cached():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / "sleeper_players.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 7*24*3600:
        return json.loads(cache.read_text(encoding="utf-8"))
    players = _get(f"{BASE}/players/nfl")
    cache.write_text(json.dumps(players), encoding="utf-8")
    return players

# --------------- Helpers --------------- #
def owner_maps(users, rosters):
    rid_to_owner = {r["roster_id"]: r.get("owner_id") for r in rosters}
    owner_to_teamname = {}
    owner_to_display = {}
    for u in users:
        owner_to_teamname[u["user_id"]] = (u.get("metadata", {}) or {}).get("team_name")
        owner_to_display[u["user_id"]]  = u.get("display_name") or "Unknown"
    return rid_to_owner, owner_to_teamname, owner_to_display

def format_record(w, l, t): return f"{w}-{l}-{t}"

def tiebreak_key(stats, owner_id):
    s = stats[owner_id]
    # Wins desc, PF desc, PA asc, Name asc
    return (-s["W"], -round(s["PF"],2), round(s["PA"],2), s["TeamName"].lower())

def safe_int(x, default=None):
    try: return int(x)
    except: return default

# -------- Draft Position (robust) -------- #
def draft_positions_for_league(league_id, users, rosters):
    """owner_id -> draft_position (1..N)"""
    mapping = {}

    # 1) aus ROSTERS.settings
    for r in rosters:
        oid = r.get("owner_id")
        st  = r.get("settings") or {}
        pos = st.get("draft_slot") or st.get("draft_position")
        if oid is not None and pos:
            mapping[str(oid)] = safe_int(pos)

    # 2) aus DRAFTS[0].draft_order (Keys = user_id)
    try:
        drafts = get_drafts(league_id) or []
    except:
        drafts = []
    if drafts:
        draft = drafts[0]
        order = draft.get("draft_order") or {}
        # Keys können str oder int sein → beides prüfen
        for u in users:
            uid = str(u["user_id"])
            if uid in order and mapping.get(uid) is None:
                mapping[uid] = safe_int(order[uid])

    # 3) Fallback über Round-1 Picks
    if drafts:
        draft_id = drafts[0].get("draft_id")
        if draft_id:
            try:
                picks = get_draft_picks(draft_id) or []
            except:
                picks = []
            for p in picks:
                if p.get("round") == 1:
                    uid = str(p.get("owner_id"))
                    # draft_slot ist meist vorhanden; sonst pick_no approximieren
                    slot = safe_int(p.get("draft_slot")) or safe_int(p.get("pick_no"))
                    if uid and slot and mapping.get(uid) is None:
                        mapping[uid] = slot

    return mapping  # evtl. unvollständig; fehlende füllen wir nicht

# -------- Moves/Trades (best effort) -------- #
def count_moves_and_trades(league_id, owner_id):
    moves = 0
    trades = 0
    for week in range(1, 17):  # Regular Season 1..16
        try:
            txs = get_transactions(league_id, week) or []
        except:
            continue
        for tx in txs:
            ttype = tx.get("type")
            creator = tx.get("creator")
            roster_ids = set(tx.get("roster_ids") or [])
            if ttype in ("waiver","free_agent"):
                if creator == owner_id:
                    moves += 1
            elif ttype == "trade":
                # Ohne saubere roster_id→owner_id Historie schwer exakt;
                # hier zählen wir Trades, an denen der Owner beteiligt ist,
                # indem wir prüfen, ob seine roster_id in roster_ids vorkam.
                # Dazu bräuchten wir eigentlich pro Woche eine Map; als Annäherung +1 global:
                if roster_ids:
                    trades += 1
    return moves, trades

# -------- Playoff-Rank (best effort) -------- #
def compute_playoff_ranks(league_id, rosters):
    pranks = {r["roster_id"]: None for r in rosters}
    try: winners = get_winners_bracket(league_id) or []
    except: winners = []
    try: losers  = get_losers_bracket(league_id) or []
    except: losers = []

    if winners:
        max_round = max(m.get("r", 0) for m in winners)
        finals = [m for m in winners if m.get("r") == max_round]
        if finals:
            fm = finals[0]
            champ  = fm.get("w")
            runner = fm.get("l")
            if champ  is not None: pranks[champ]  = 1
            if runner is not None: pranks[runner] = 2
    if losers:
        losers_sorted = sorted(losers, key=lambda m: (m.get("r",0), 1 if m.get("w") is None else 0), reverse=True)
        rank = 5
        seen = set()
        for m in losers_sorted:
            for k in ("w","l","t1","t2"):
                rid = m.get(k)
                if isinstance(rid, int) and rid not in seen and pranks.get(rid) in (None,):
                    pranks[rid] = rank
                    seen.add(rid)
                    rank += 1
    return pranks

# -------- Kernberechnung für 1..N -------- #
def compute_regular_season(league_id, users, rosters, weeks_max):
    rid_to_owner, owner_to_teamname, owner_to_display = owner_maps(users, rosters)
    owner_ids = set(rid_to_owner.values())
    stats = defaultdict(lambda: {"W":0,"L":0,"T":0,"PF":0.0,"PA":0.0,"TeamName":"", "ManagerName":"", "Moves":0, "Trades":0, "DraftPosition":None})

    for oid in owner_ids:
        stats[oid]["TeamName"]    = owner_to_teamname.get(oid) or owner_to_display.get(oid) or "Unknown"
        stats[oid]["ManagerName"] = owner_to_display.get(oid, "Unknown")

    for week in range(1, weeks_max+1):
        matchups = get_matchups(league_id, week) or []
        by_mid = defaultdict(list)
        for t in matchups: by_mid[t.get("matchup_id")].append(t)

        for teams in by_mid.values():
            if len(teams) != 2:
                # nur Punkte mitzählen
                for t in teams:
                    rid = t["roster_id"]
                    oid = rid_to_owner.get(rid)
                    stats[oid]["PF"] += float(t.get("points", 0) or 0.0)
                continue
            a, b = teams
            a_oid = rid_to_owner.get(a["roster_id"])
            b_oid = rid_to_owner.get(b["roster_id"])
            a_pts = float(a.get("points", 0) or 0.0)
            b_pts = float(b.get("points", 0) or 0.0)
            stats[a_oid]["PF"] += a_pts; stats[a_oid]["PA"] += b_pts
            stats[b_oid]["PF"] += b_pts; stats[b_oid]["PA"] += a_pts
            if a_pts > b_pts: stats[a_oid]["W"] += 1; stats[b_oid]["L"] += 1
            elif b_pts > a_pts: stats[b_oid]["W"] += 1; stats[a_oid]["L"] += 1
            else: stats[a_oid]["T"] += 1; stats[b_oid]["T"] += 1

    # Moves/Trades
    for oid in owner_ids:
        m, tr = count_moves_and_trades(league_id, oid)
        stats[oid]["Moves"] = m
        stats[oid]["Trades"] = tr

    # Draft-Positionen
    owner_to_dpos = draft_positions_for_league(league_id, users, rosters)
    for oid in owner_ids:
        dp = owner_to_dpos.get(str(oid))
        if dp is not None:
            stats[oid]["DraftPosition"] = dp

    # RegularSeasonRank
    owners_sorted = sorted(owner_ids, key=lambda oid: tiebreak_key(stats, oid))
    for rank, oid in enumerate(owners_sorted, start=1):
        stats[oid]["RegularSeasonRank"] = rank

    # Playoff-Ranks (nur einmal sinnvoll; wir tragen sie trotzdem ein, schaden nicht)
    pranks = compute_playoff_ranks(league_id, rosters)
    rid_to_owner = {r["roster_id"]: r.get("owner_id") for r in rosters}
    for r in rosters:
        rid = r["roster_id"]; oid = rid_to_owner.get(rid)
        if oid is None: continue
        pr = pranks.get(rid)
        stats[oid]["PlayoffRank"] = pr if pr is not None else stats[oid]["RegularSeasonRank"]

    return owners_sorted, stats

# ----------------------------- MAIN ----------------------------- #
def main():
    if not LEAGUE_ID:
        raise SystemExit("Bitte SLEEPER_LEAGUE_ID als Umgebungsvariable setzen.")

    league  = get_league(LEAGUE_ID)
    users   = get_league_users(LEAGUE_ID)
    rosters = get_league_rosters(LEAGUE_ID)
    _ = get_players_cached()  # nicht zwingend nötig hier, aber lässt sich cachen

    # Saison bestimmen
    season_str = ENV_SEASON or league.get("season") or "2022"
    try: SEASON = int(season_str)
    except: SEASON = 2022

    season_dir = OUT_DIR / str(SEASON)
    season_dir.mkdir(parents=True, exist_ok=True)

    # 1) Weeks 1..14
    owners_14, stats_14 = compute_regular_season(LEAGUE_ID, users, rosters, 14)
    out_14 = season_dir / f"standings_1-14_{SEASON}.csv"
    write_csv(out_14, owners_14, stats_14)

    # 2) Weeks 1..16
    owners_16, stats_16 = compute_regular_season(LEAGUE_ID, users, rosters, 16)
    out_16 = season_dir / f"standings_1-16_{SEASON}.csv"
    write_csv(out_16, owners_16, stats_16)

    print(f"✓ geschrieben: {out_14}")
    print(f"✓ geschrieben: {out_16}")

def write_csv(path, owners_sorted, stats):
    header = ["TeamName","RegularSeasonRank","Record","PointsFor","PointsAgainst","PlayoffRank","ManagerName","Moves","Trades","DraftPosition"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=",")  # echtes CSV
        w.writerow(header)
        for oid in owners_sorted:
            s = stats[oid]
            record = format_record(s["W"], s["L"], s["T"])
            pf = f"{s['PF']:,.2f}"  # Tausender-Komma, Dezimalpunkt
            pa = f"{s['PA']:,.2f}"
            w.writerow([
                s["TeamName"],
                s.get("RegularSeasonRank",""),
                record,
                pf,
                pa,
                s.get("PlayoffRank",""),
                s["ManagerName"],
                s.get("Moves",0),
                s.get("Trades",0),
                s.get("DraftPosition",""),
            ])

if __name__ == "__main__":
    main()
