# scrapeSleeperDraft.py
import os, json, csv, time
from pathlib import Path
import requests

BASE = "https://api.sleeper.app/v1"
OUT_DIR = Path("./output")
DATA_DIR = Path("./data")

LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID", "").strip()
ENV_SEASON = os.getenv("SEASON")  # optional

def _get(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def get_league(league_id):       return _get(f"{BASE}/league/{league_id}")
def get_users(league_id):        return _get(f"{BASE}/league/{league_id}/users")
def get_rosters(league_id):      return _get(f"{BASE}/league/{league_id}/rosters")
def get_drafts(league_id):       return _get(f"{BASE}/league/{league_id}/drafts")
def get_draft_picks(draft_id):   return _get(f"{BASE}/draft/{draft_id}/picks")
def get_players_cached():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / "sleeper_players.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 7*24*3600:
        return json.loads(cache.read_text(encoding="utf-8"))
    players = _get(f"{BASE}/players/nfl")
    cache.write_text(json.dumps(players), encoding="utf-8")
    return players

def short_name(player):
    if not player: return ""
    first = player.get("first_name") or ""
    last  = player.get("last_name")  or (player.get("full_name") or "").split(" ")[-1]
    return f"{(first[:1]+'. ') if first else ''}{last}".strip()

def fmt_player(pdb, pid):
    if not pid: return "", "", ""
    p = pdb.get(pid) or {}
    pos  = p.get("position") or ""
    team = p.get("team") or p.get("metadata", {}).get("team_abbr") or ""
    name = p.get("full_name") or (short_name(p) if (p.get("first_name") or p.get("last_name")) else pid)
    return name, pos, team

def main():
    if not LEAGUE_ID:
        raise SystemExit("Bitte SLEEPER_LEAGUE_ID setzen.")

    league   = get_league(LEAGUE_ID)
    users    = get_users(LEAGUE_ID)
    rosters  = get_rosters(LEAGUE_ID)
    players  = get_players_cached()
    season_str = ENV_SEASON or league.get("season") or "2022"
    try: SEASON = int(season_str)
    except: SEASON = 2022

    season_dir = OUT_DIR / str(SEASON)
    season_dir.mkdir(parents=True, exist_ok=True)

    # Maps
    user_display  = {u["user_id"]: (u.get("display_name") or "Unknown") for u in users}
    user_teamname = {u["user_id"]: (u.get("metadata", {}) or {}).get("team_name") or user_display[u["user_id"]] for u in users}

    drafts = get_drafts(LEAGUE_ID) or []
    if not drafts:
        print("Kein Draft gefunden.")
        return
    draft = drafts[0]  # meist nur einer
    draft_id = draft["draft_id"]
    draft_order = draft.get("draft_order") or {}  # user_id -> slot

    # inverse Map: slot -> user_id (Original Owner dieses Slots)
    slot_to_user = {}
    for uid, slot in draft_order.items():
        if slot is not None:
            slot_to_user[int(slot)] = uid

    picks = get_draft_picks(draft_id) or []
    # Sortierung sicherstellen: nach overall pick_no
    picks.sort(key=lambda p: int(p.get("pick_no") or 0))

    out_path = season_dir / "draft.tsv"
    header = ["Round","Overall","PickInRound","TeamName","ManagerName","OriginalSlot","PickedByUser","Player","Pos","NFLTeam","Keeper","Notes"]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(header)

        for pk in picks:
            rnd  = int(pk.get("round") or 0)
            overall = int(pk.get("pick_no") or 0)
            slot = pk.get("draft_slot")  # 1..N, ursprünglicher Slot dieser Position in der Snake
            try:
                slot = int(slot) if slot is not None else None
            except:
                slot = None

            picked_by = pk.get("picked_by")  # user_id, der diesen Pick tatsächlich getätigt hat
            picked_name = user_display.get(picked_by, "") if picked_by else ""
            picked_team = user_teamname.get(picked_by, "") if picked_by else ""

            # OriginalSlot-Owner (der Slot gehört eigentlich diesem User vor Trades)
            original_uid = slot_to_user.get(slot)
            original_name = user_display.get(original_uid, "") if original_uid else ""

            # Spieler
            player_id = pk.get("player_id")
            name, pos, nfl = fmt_player(players, player_id)

            # Keeper?
            meta = pk.get("metadata") or {}
            keeper = "Yes" if str(meta.get("keeper", "")).lower() in ("1","true","yes") else ""

            # Notes: markiere „via Slot X“, wenn der Picker ≠ ursprünglicher Slot-Owner
            notes = ""
            if picked_by and original_uid and str(picked_by) != str(original_uid):
                notes = f"via Slot {slot} ({original_name})"

            # Pick in Round (1..N in der Runde)
            # Snake: pick_in_round kann aus overall und Rundenlänge abgeleitet werden, aber Sleeper liefert kein teams_count hier direkt.
            # Näherung: wenn slot vorhanden, dann pick_in_round = slot in ungeraden Runden, sonst rückwärts in geraden Runden.
            pick_in_round = slot if slot else ""
            # Wenn du exakt die Snake-Logik willst, kann man teams_count = max(draft_order.values()) nehmen:
            if draft_order:
                teams_count = max(int(v) for v in draft_order.values() if v)
                if slot:
                    if rnd % 2 == 1:
                        pick_in_round = slot
                    else:
                        pick_in_round = (teams_count - slot + 1)

            w.writerow([
                rnd,
                overall,
                pick_in_round,
                picked_team,
                picked_name,
                slot or "",
                picked_by or "",
                name,
                pos,
                nfl,
                keeper,
                notes
            ])

    print(f"✓ Draft exportiert: {out_path}")

if __name__ == "__main__":
    main()
