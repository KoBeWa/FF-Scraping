import csv, json
from pathlib import Path
from collections import defaultdict

# <<< HIER ist jetzt dein echter Datenpfad >>>
# Struktur: output/teamgamecenter/<SEASON>/<WEEK>.csv  (z.B. output/teamgamecenter/2015/1.csv)
RAW_DIR = Path("output/teamgamecenter")

OUT_DIR = Path("data/processed/seasons")

# ---------- kleine Utilities ----------
def safe_float(x):
    if x is None: return None
    s = str(x).strip()
    if s in ("", "-", "nan", "NaN"): return None
    try: return float(s.replace(",", ""))
    except: return None

def extract_pos(p):
    if not p: return None
    s = p.upper()
    for t in (" QB ", " RB ", " WR ", " TE ", " K ", " DEF "):
        if t in s: return t.strip()
    for t in ("QB","RB","WR","TE","K","DEF"):
        if s.endswith(t) or s.startswith(t): return t
    return None

def norm(s: str) -> str:
    """Normalize header names: lowercase, remove spaces/underscores/dots."""
    return "".join(ch for ch in s.lower() if ch.isalnum())

def idx(header, *candidates):
    """Find index of a header by trying several candidate names (robust gegen Varianten)."""
    hmap = {norm(h): i for i, h in enumerate(header)}
    for c in candidates:
        k = norm(c)
        if k in hmap: return hmap[k]
    raise KeyError(f"Spalte nicht gefunden. Gesucht: {candidates}; vorhanden: {header}")

# ---------- Kern-Parser ----------
def parse_team_row(header, row):
    gi_owner     = idx(header, "Owner", "Team", "Manager", "Owner Name")
    gi_opponent  = idx(header, "Opponent", "Opp", "Opponent Team", "Gegner")
    gi_total     = idx(header, "Total", "Total Points", "Pts", "Summe")
    gi_opp_total = idx(header, "Opponent Total", "OpponentTotal", "Opp Total", "Gegner Punkte")

    owner = row[gi_owner].strip()
    opponent = row[gi_opponent].strip()
    total = safe_float(row[gi_total])
    opp_total = safe_float(row[gi_opp_total])

    # Paare: Slot, Points … mehrfach; Starter vs BN unterscheiden
    starters_order = ["QB","RB","RB","WR","WR","TE","W/R","K","DEF"]
    starters, bench = [], []

    # Ab "Rank" nach vorne parsen, bis vor "Total"
    gi_rank = idx(header, "Rank")
    # Position von "Total" als Ende:
    end_i = idx(header, "Total", "Total Points", "Pts", "Summe")
    i = gi_rank + 1
    slot_buf = None

    while i < end_i and i < len(header):
        col = header[i]
        val = row[i].strip() if i < len(row) and row[i] is not None else ""
        if norm(col) == "points":
            if slot_buf is not None:
                slot, player_raw = slot_buf
                ent = {"slot": slot, "player_raw": player_raw.strip(),
                       "pos": extract_pos(player_raw), "points": safe_float(val)}
                (bench if slot.upper()=="BN" else starters).append(ent)
                slot_buf = None
        else:
            # das ist ein Slot-Feld (QB/RB/WR/TE/W/R/K/DEF/BN)
            slot_buf = (col.strip(), val)
        i += 1

    def s_key(e):
        try: return starters_order.index(e["slot"])
        except ValueError: return 999
    starters_sorted = sorted([e for e in starters if e["slot"].upper() != "BN"], key=s_key)

    return {"owner": owner, "opponent": opponent, "total": total, "opponent_total": opp_total,
            "starters": starters_sorted, "bench": bench}

def group_matchups(team_rows):
    bucket = defaultdict(list)
    for r in team_rows:
        bucket[frozenset((r["owner"], r["opponent"]))].append(r)
    matchups = []
    for _, sides in bucket.items():
        if len(sides) != 2: 
            # ungültig/bye → überspringen
            continue
        a, b = sides
        home, away = (a, b) if a["owner"] <= b["owner"] else (b, a)
        matchups.append({
            "home_team": home["owner"], "away_team": away["owner"],
            "home_points": home["total"], "away_points": away["total"],
            "home_lineup": {"starters": home["starters"], "bench": home["bench"]},
            "away_lineup": {"starters": away["starters"], "bench": away["bench"]},
        })
    return matchups

def parse_week_file(path: Path, season: int, week: int):
    # unterstützt CSV und TSV
    with path.open("r", encoding="utf-8") as f:
        # Trennzeichen automatisch: zuerst versuchen wir CSV (Komma),
        # falls nur 1 Spalte, nehmen wir Tab.
        peek = f.readline()
        f.seek(0)
        reader = csv.reader(f) if (peek.count(",") >= peek.count("\t")) else csv.reader(f, delimiter="\t")
        rows = list(reader)
    header, rows = rows[0], rows[1:]

    # Minimal-Header prüfen
    _ = idx(header, "Owner", "Team", "Manager")           # throws if not found
    _ = idx(header, "Opponent", "Opp", "Opponent Team")
    _ = idx(header, "Rank")
    _ = idx(header, "Total", "Total Points", "Pts")
    _ = idx(header, "Opponent Total", "OpponentTotal", "Opp Total")

    team_rows, players = [], []
    for row in rows:
        if not row or all(c.strip()=="" for c in row): 
            continue
        team = parse_team_row(header, row)
        team_rows.append(team)
        # Flatten zu players_games
        def emit(lineup, is_starter):
            for e in lineup:
                players.append({
                    "season": season, "week": week, "manager": team["owner"], "opponent": team["opponent"],
                    "slot": e["slot"], "pos": e["pos"], "player_raw": e["player_raw"],
                    "points": e["points"], "is_starter": is_starter
                })
        emit(team["starters"], True)
        emit(team["bench"], False)
    return team_rows, players

def build_season(season_dir: Path, season: int):
    # deine Dateien heißen "1.csv", "2.csv" ... (ggf. auch .tsv)
    week_files = sorted(season_dir.glob("*.csv")) + sorted(season_dir.glob("*.tsv"))
    all_matchups, all_players = [], []
    stats = defaultdict(lambda: {"pf":0.0,"pa":0.0,"wins":0,"losses":0,"ties":0})

    for wf in week_files:
        # Week = Dateiname ohne Endung (z.B. "1")
        try:
            wk = int(wf.stem)
        except ValueError:
            continue
        team_rows, players = parse_week_file(wf, season, wk)
        week_m = group_matchups(team_rows)
        for m in week_m:
            m["season"] = season; m["week"] = wk
            m["is_playoff"] = False  # in diesem Pfad sind's Regular-Season-Files
            all_matchups.append(m)
            hp, ap = (m["home_points"] or 0.0), (m["away_points"] or 0.0)
            ht, at = m["home_team"], m["away_team"]
            stats[ht]["pf"] += hp; stats[ht]["pa"] += ap
            stats[at]["pf"] += ap; stats[at]["pa"] += hp
            if hp == ap: stats[ht]["ties"] += 1; stats[at]["ties"] += 1
            elif hp > ap: stats[ht]["wins"] += 1; stats[at]["losses"] += 1
            else:         stats[at]["wins"] += 1; stats[ht]["losses"] += 1
        all_players.extend(players)

    out = OUT_DIR / f"{season}"
    out.mkdir(parents=True, exist_ok=True)
    (out/"matchups.json").write_text(json.dumps(all_matchups, ensure_ascii=False), encoding="utf-8")
    (out/"players_games.json").write_text(json.dumps(all_players, ensure_ascii=False), encoding="utf-8")

    teams = [{"season": season, "team": t, "wins": v["wins"], "losses": v["losses"], "ties": v["ties"],
              "pf": round(v["pf"],2), "pa": round(v["pa"],2),
              "seed": None, "playoff_rank": None,
              "elo_end": None, "luck": None, "sos": None,
              "optimal_lineup_eff": None, "waiver_points": None, "bench_points_wasted": None}
             for t,v in sorted(stats.items())]
    (out/"teams.json").write_text(json.dumps(teams, ensure_ascii=False), encoding="utf-8")

    print(f"✓ {season}: {len(all_matchups)} matchups, {len(all_players)} player-games, {len(teams)} teams")

def run_all(seasons=range(2015, 2026)):
    for season in seasons:
        sd = RAW_DIR / str(season)
        if not sd.exists():
            print(f"– skip {season}, missing {sd}")
            continue
        build_season(sd, season)

if __name__ == "__main__":
    run_all()
