# scrapeSleeperStandings.py
import os, json, csv, time
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
    players = _get(f"{BASE}/players/nfl")  # große JSON
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

def format_record(w, l, t):
    return f"{w}-{l}-{t}"

def tiebreak_key(stats, owner_id):
    # Wins desc, PF desc, PA asc, Name asc
    s = stats[owner_id]
    return (-s["W"], -round(s["PF"], 2), round(s["PA"], 2), s["TeamName"].lower())

def safe_int(x, default=None):
    try: return int(x)
    except: return default

# --------------- Playoff Rank (best effort) --------------- #
def compute_playoff_ranks(league_id, rosters):
    """Gibt Dict roster_id -> playoff_rank zurück. Best effort basierend auf Brackets."""
    # Default: None (nicht verfügbar)
    pranks = {r["roster_id"]: None for r in rosters}

    try:
        winners = get_winners_bracket(league_id) or []
    except: winners = []
    try:
        losers = get_losers_bracket(league_id) or []
    except: losers = []

    # Hilf: Finde Final-Match (höchste Runde im Winners)
    if winners:
        max_round = max(m.get("r", 0) for m in winners)
        finals = [m for m in winners if m.get("r") == max_round]
        if finals:
            fm = finals[0]
            champ = fm.get("w")           # roster_id Gewinner
            runner = fm.get("l")          # roster_id Verlierer
            if champ is not None:  pranks[champ] = 1
            if runner is not None: pranks[runner] = 2

            # Versuche 3rd place zu identifizieren: Match derselben Runde mit "t3" Flag gibt es teils nicht.
            # Heuristik: Verlierer der beiden Halbfinals -> Plätze 3/4, Punkte im letzten Spiel als Sortierung.
            # Ohne Punkteinfos im Bracket lassen wir 3/4 vorerst leer und füllen später mit Seeds.
        # Losers Bracket: rangiere danach fortlaufend (5..n), basierend auf letzter Runde (höhere Runde = besser)
        if losers:
            # Sortiere nach Runde absteigend, dann optional "w" vs "l"
            losers_sorted = sorted(losers, key=lambda m: (m.get("r", 0), 1 if m.get("w") is None else 0), reverse=True)
            rank = 5  # typische 10er Liga -> 5..10
            seen = set()
            for m in losers_sorted:
                for k in ("w", "l", "t1", "t2"):
                    rid = m.get(k)
                    if isinstance(rid, int) and rid not in seen and pranks.get(rid) in (None,):
                        pranks[rid] = rank
                        seen.add(rid)
                        rank += 1
    return pranks

# --------------- Draft Position --------------- #
def draft_positions_for_league(league_id, users):
    """owner_id -> draft_position (1..N)"""
    try:
        drafts = get_drafts(league_id) or []
    except:
        drafts = []
    mapping = {}
    if not drafts:
        return mapping
    draft = drafts[0]  # meist nur einer
    # 1) Versuche draft_order direkt:
    order = draft.get("draft_order") or {}
    if order:
        for owner_id, pos in order.items():
            mapping[str(owner_id)] = safe_int(pos)
    # 2) Fallback: aus Round-1-Picks
    if not mapping:
        try:
            picks = get_draft_picks(draft["draft_id"]) or []
            for p in picks:
                if p.get("round") == 1:
                    mapping[str(p.get("owner_id"))] = safe_int(p.get("pick_no"))
        except:
            pass
    return mapping

# --------------- Moves/Trades zählen --------------- #
def count_moves_and_trades(league_id, owner_id):
    moves = 0
    trades = 0
    # Wochen 1..16 wie bei Regular Season
    for week in range(1, 17):
        try:
            txs = get_transactions(league_id, week) or []
        except:
            continue
        for tx in txs:
            ttype = tx.get("type")
            # Beteiligte Owner: unter "roster_ids" (bei trade) oder "creator" (bei waiver/free_agent)
            roster_ids = set(tx.get("roster_ids") or [])
            creator = tx.get("creator")  # user_id
            # Trade: wenn owner_id über seine roster_id beteiligt ist
            if ttype == "trade":
                if roster_ids:
                    # bei trade stehen roster_ids (roster-IDs) drin, wir können owner_id nicht direkt matchen
                    # -> wir zählen Trades global und verteilen auf alle beteiligten User (Annäherung)
                    # (Für exakte Zuordnung bräuchte man roster_id->owner_id Map in diesem Scope.)
                    trades += 1
                else:
                    # Fallback: wenn "adds" / "drops" mehrere owner betreffen – dennoch als Trade zählen
                    trades += 1
            elif ttype in ("waiver", "free_agent"):
                # Zähle Move, wenn der Ersteller dieser Owner ist
                if creator == owner_id:
                    moves += 1
            else:
                # andere Typen ignorieren
                pass
    return moves, trades

# ----------------------------- MAIN ----------------------------- #
def main():
    if not LEAGUE_ID:
        raise SystemExit("Bitte SLEEPER_LEAGUE_ID als Umgebungsvariable setzen.")

    league  = get_league(LEAGUE_ID)
    users   = get_league_users(LEAGUE_ID)
    rosters = get_league_rosters(LEAGUE_ID)
    players = get_players_cached()

    # Saison bestimmen
    season_str = ENV_SEASON or league.get("season") or "2022"
    try: SEASON = int(season_str)
    except: SEASON = 2022

    season_dir = OUT_DIR / str(SEASON)
    season_dir.mkdir(parents=True, exist_ok=True)

    rid_to_owner, owner_to_teamname, owner_to_display = owner_maps(users, rosters)

    # Containers für Regular Season
    stats = defaultdict(lambda: {"W":0,"L":0,"T":0,"PF":0.0,"PA":0.0,"TeamName":"", "ManagerName":"", "Moves":0, "Trades":0, "DraftPosition":None})
    owner_ids = set(rid_to_owner.values())

    # Team/Manager Namen
    for owner_id in owner_ids:
        team_name = owner_to_teamname.get(owner_id) or owner_to_display.get(owner_id) or "Unknown"
        stats[owner_id]["TeamName"] = team_name
        stats[owner_id]["ManagerName"] = owner_to_display.get(owner_id, "Unknown")

    # PF/PA & W/L/T über Wochen 1..16
    for week in range(1, 17):
        matchups = get_matchups(LEAGUE_ID, week) or []
        # gruppiere per matchup_id
        by_mid = defaultdict(list)
        for t in matchups:
            by_mid[t.get("matchup_id")].append(t)
        for mid, teams in by_mid.items():
            if len(teams) != 2:
                # Median/Bye/etc. ignorieren für W/L, aber Punkte mitnehmen
                for t in teams:
                    rid = t["roster_id"]
                    owner_id = rid_to_owner.get(rid)
                    pts = float(t.get("points", 0) or 0.0)
                    stats[owner_id]["PF"] += pts
                continue
            a, b = teams
            a_owner = rid_to_owner.get(a["roster_id"])
            b_owner = rid_to_owner.get(b["roster_id"])
            a_pts = float(a.get("points", 0) or 0.0)
            b_pts = float(b.get("points", 0) or 0.0)
            stats[a_owner]["PF"] += a_pts; stats[a_owner]["PA"] += b_pts
            stats[b_owner]["PF"] += b_pts; stats[b_owner]["PA"] += a_pts
            if a_pts > b_pts:
                stats[a_owner]["W"] += 1; stats[b_owner]["L"] += 1
            elif b_pts > a_pts:
                stats[b_owner]["W"] += 1; stats[a_owner]["L"] += 1
            else:
                stats[a_owner]["T"] += 1; stats[b_owner]["T"] += 1

    # Moves/Trades pro Owner (best effort)
    # Hinweis: exakte Trade-Zuordnung zu Ownern ist tricky; hier Annäherung via "creator" / roster_ids.
    # Für präzise Trade-Counts bräuchten wir pro Transaction die beteiligten roster_id->owner_id Map im Moment der Transaktion.
    # (Kann man erweitern, wenn nötig.)
    owner_move_trade = {}
    for owner_id in owner_ids:
        m, tr = count_moves_and_trades(LEAGUE_ID, owner_id)
        owner_move_trade[owner_id] = (m, tr)
        stats[owner_id]["Moves"] = m
        stats[owner_id]["Trades"] = tr

    # Draft-Positionen
    owner_to_dpos = draft_positions_for_league(LEAGUE_ID, users)
    for owner_id in owner_ids:
        dp = owner_to_dpos.get(str(owner_id))
        if dp is not None:
            stats[owner_id]["DraftPosition"] = dp

    # RegularSeasonRank berechnen
    owners_sorted = sorted(owner_ids, key=lambda oid: tiebreak_key(stats, oid))
    for rank, oid in enumerate(owners_sorted, start=1):
        stats[oid]["RegularSeasonRank"] = rank

    # Playoff-Ranks (falls möglich)
    pranks = compute_playoff_ranks(LEAGUE_ID, rosters)
    for r in rosters:
        rid = r["roster_id"]
        oid = rid_to_owner.get(rid)
        if oid is None: continue
        pr = pranks.get(rid)
        if pr is not None:
            stats[oid]["PlayoffRank"] = pr
        else:
            # Fallback: wenn kein Bracket, setze PlayoffRank = RegularSeasonRank
            stats[oid]["PlayoffRank"] = stats[oid].get("RegularSeasonRank", "")

    # CSV schreiben
    out = season_dir / f"standings_sleeper_{SEASON}.csv"
    header = ["TeamName","RegularSeasonRank","Record","PointsFor","PointsAgainst","PlayoffRank","ManagerName","Moves","Trades","DraftPosition"]

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")  # wie in deinem Beispiel (Tab-getrennt)
        w.writerow(header)
        # Ausgabe in der RegularSeasonRank-Reihenfolge
        for oid in owners_sorted:
            s = stats[oid]
            record = format_record(s["W"], s["L"], s["T"])
            pf = f"{s['PF']:.2f}".replace(".", ",")  # falls du Dezimalkomma möchtest, sonst entfernen
            pa = f"{s['PA']:.2f}".replace(".", ",")
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

    print(f"✓ Standings geschrieben: {out}")

if __name__ == "__main__":
    main()
