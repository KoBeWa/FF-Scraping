import csv, json
from pathlib import Path
from collections import defaultdict

# TeamGameCenter: output/teamgamecenter/<SEASON>/<WEEK>.csv
RAW_DIR = Path("output/teamgamecenter")
OUT_DIR = Path("data/processed/seasons")

# History-Standings (TSV):
HIST_DIR = Path("output/history-standings")  # <season>.tsv und playoffs-<season>.tsv

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
    return "".join(ch for ch in s.lower() if ch.isalnum())

def idx(header, *candidates):
    hmap = {norm(h): i for i, h in enumerate(header)}
    for c in candidates:
        k = norm(c)
        if k in hmap: return hmap[k]
    raise KeyError(f"Spalte nicht gefunden. Gesucht: {candidates}; vorhanden: {header}")

def parse_team_row(header, row):
    gi_owner     = idx(header, "Owner", "Team", "Manager", "Owner Name")
    gi_opponent  = idx(header, "Opponent", "Opp", "Opponent Team", "Gegner")
    gi_total     = idx(header, "Total", "Total Points", "Pts", "Summe")
    gi_opp_total = idx(header, "Opponent Total", "OpponentTotal", "Opp Total", "Gegner Punkte")

    owner = row[gi_owner].strip()
    opponent = row[gi_opponent].strip()
    total = safe_float(row[gi_total])
    opp_total = safe_float(row[gi_opp_total])

    starters_order = ["QB","RB","RB","WR","WR","TE","W/R","K","DEF"]
    starters, bench = [], []
    gi_rank = idx(header, "Rank")
    end_i = gi_total
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
    with path.open("r", encoding="utf-8") as f:
        peek = f.readline()
        f.seek(0)
        reader = csv.reader(f) if (peek.count(",") >= peek.count("\t")) else csv.reader(f, delimiter="\t")
        rows = list(reader)
    header, rows = rows[0], rows[1:]

    _ = idx(header, "Owner", "Team", "Manager")
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

# ---------- NEU: Weekly Standings aus Matchups ----------
def build_weekly_standings(all_week_matchups):
    """
    all_week_matchups: dict[int -> list[matchup dict]]
    Liefert: [{"week": w, "rows":[{team, wins, losses, pf, pa, pct, rank}...]}...]
    Sortierung: wins desc, pf desc, team asc
    """
    weekly = []
    for w in sorted(all_week_matchups.keys()):
        # pro Team die weekly Zahlen (nur diese Woche, nicht kumulativ)
        table = defaultdict(lambda: {"wins":0,"losses":0,"ties":0,"pf":0.0,"pa":0.0})
        for m in all_week_matchups[w]:
            ht, at = m["home_team"], m["away_team"]
            hp, ap = (m["home_points"] or 0.0), (m["away_points"] or 0.0)
            table[ht]["pf"] += hp; table[ht]["pa"] += ap
            table[at]["pf"] += ap; table[at]["pa"] += hp
            if hp == ap: table[ht]["ties"] += 1; table[at]["ties"] += 1
            elif hp > ap: table[ht]["wins"] += 1; table[at]["losses"] += 1
            else:         table[at]["wins"] += 1; table[ht]["losses"] += 1

        rows = []
        for team, v in table.items():
            games = v["wins"] + v["losses"] + v["ties"]
            pct = (v["wins"] + 0.5 * v["ties"]) / games if games else 0.0
            rows.append({
                "team": team,
                "wins": v["wins"], "losses": v["losses"], "ties": v["ties"],
                "pf": round(v["pf"],2), "pa": round(v["pa"],2),
                "pct": round(pct,4)
            })

        rows.sort(key=lambda r: (-r["wins"], -r["pf"], r["team"]))
        for i, r in enumerate(rows, start=1):
            r["rank"] = i
        weekly.append({"week": w, "rows": rows})
    return weekly

# ---------- NEU: TSV-Parser für RegSeason-Finale & Playoffs ----------
def read_tsv(path: Path):
    with path.open("r", encoding="utf-8") as f:
        rdr = csv.DictReader(f, delimiter="\t")
        return list(rdr)

def build_regular_final_from_tsv(season: int):
    """
    Liest output/history-standings/<season>.tsv mit Spalten:
    TeamName, RegularSeasonRank, Record, PointsFor, PointsAgainst, PlayoffRank, ManagerName, Moves, Trades, DraftPosition
    und gibt eine sortierte Liste von Dicts zurück.
    """
    tsv = HIST_DIR / f"{season}.tsv"
    if not tsv.exists():
        return None

    def _safe_float_num(s):
        if s is None or str(s).strip() == "":
            return None
        # entfernt Tausendertrenn-Kommas, behält Dezimalpunkt
        return float(str(s).replace(",", ""))

    rows = read_tsv(tsv)
    out = []
    for r in rows:
        team   = r.get("TeamName")
        rank   = r.get("RegularSeasonRank")
        record = r.get("Record")
        pf     = _safe_float_num(r.get("PointsFor"))
        pa     = _safe_float_num(r.get("PointsAgainst"))

        playoff_rank = r.get("PlayoffRank")
        manager      = r.get("ManagerName")
        moves        = r.get("Moves")
        trades       = r.get("Trades")
        draft_pos    = r.get("DraftPosition")

        # optional: Record in W/L/T zerlegen
        w = l = t = None
        if isinstance(record, str) and "-" in record:
            parts = record.split("-")
            if len(parts) >= 2:
                try: w = int(parts[0])
                except: pass
                try: l = int(parts[1])
                except: pass
                if len(parts) >= 3:
                    try: t = int(parts[2])
                    except: pass

        out.append({
            "team": team,
            "regular_rank": int(rank) if rank not in (None, "",) else None,
            "record": record,
            "wins": w, "losses": l, "ties": t,
            "pf": pf, "pa": pa,

            # Zusatzfelder aus TSV:
            "playoff_rank": int(playoff_rank) if playoff_rank not in (None,"") else None,
            "manager": manager,
            "moves": int(moves) if moves not in (None,"") else None,
            "trades": int(trades) if trades not in (None,"") else None,
            "draft_position": int(draft_pos) if draft_pos not in (None,"") else None,
        })

    # sortiert nach RegularSeasonRank, dann Teamname
    out.sort(key=lambda x: (x["regular_rank"] if x["regular_rank"] is not None else 999, x["team"] or ""))
    return out

def build_playoffs_from_tsv(season: int):
    tsv = HIST_DIR / f"playoffs-{season}.tsv"
    if not tsv.exists(): return None
    rows = read_tsv(tsv)
    out = []
    for r in rows:
        out.append({
            "team": r.get("TeamName") or r.get("Team"),
            "playoff_rank": int(r.get("PlayoffRank")) if r.get("PlayoffRank") else None,
            "manager": r.get("ManagerName"),
            "seed": int(r.get("Seed")) if r.get("Seed") else None,
            "week15": safe_float(r.get("Week15Pts")),
            "week16": safe_float(r.get("Week16Pts"))
        })
    out.sort(key=lambda x: (x["playoff_rank"] if x["playoff_rank"] is not None else 999, x["team"] or ""))
    return out

def build_season(season_dir: Path, season: int):
    # 1) Wochen matchups/players wie bisher
    week_files = sorted(season_dir.glob("*.csv")) + sorted(season_dir.glob("*.tsv"))
    all_matchups, all_players = [], []
    stats = defaultdict(lambda: {"pf":0.0,"pa":0.0,"wins":0,"losses":0,"ties":0})
    by_week = defaultdict(list)   # ← für weekly standings

    for wf in week_files:
        try:
            wk = int(wf.stem)
        except ValueError:
            continue
        team_rows, players = parse_week_file(wf, season, wk)
        week_m = group_matchups(team_rows)
        for m in week_m:
            m["season"] = season; m["week"] = wk; m["is_playoff"] = False
            all_matchups.append(m)
            by_week[wk].append(m)

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

    # 2) NEU: weekly standings aus by_week
    weekly = build_weekly_standings(by_week)
    (out/"weekly_standings.json").write_text(json.dumps(weekly, ensure_ascii=False), encoding="utf-8")

    # 3) NEU: TSVs für finale RegSeason & Playoffs (falls vorhanden)
    reg_final = build_regular_final_from_tsv(season)
    if reg_final is not None:
        (out/"regular_final_standings.json").write_text(json.dumps(reg_final, ensure_ascii=False), encoding="utf-8")

    playoffs = build_playoffs_from_tsv(season)
    if playoffs is not None:
        (out/"playoffs_standings.json").write_text(json.dumps(playoffs, ensure_ascii=False), encoding="utf-8")

    print(f"✓ {season}: {len(all_matchups)} matchups, {len(all_players)} player-games, {len(teams)} teams, weekly={len(weekly)}")

def run_all(seasons=range(2015, 2026)):
    for season in seasons:
        sd = RAW_DIR / str(season)
        if not sd.exists():
            print(f"– skip {season}, missing {sd}")
            continue
        build_season(sd, season)

if __name__ == "__main__":
    run_all()
