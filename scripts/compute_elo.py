#!/usr/bin/env python3
import csv, json, math, os, glob
from collections import defaultdict

# ==== Pfade (an dein Repo angepasst) ====
# Weekly Matchups liegen so wie bei dir: output/teamgamecenter/<year>/<week>.csv
WEEKLY_DIR = "output/teamgamecenter"
# Ausgaben:
ELO_DIR = "output/elo-history"
ELO_TSV = os.path.join(ELO_DIR, "elo_ratings_history.tsv")
ELO_JSON = "public/data/league/elo_history.json"   # für die Website

# ==== Elo-Parameter ====
BASE_RATING = 1500.0
K_BASE = 20.0
MEAN_REGRESSION = 0.75  # am Seasonstart: R' = 0.75*R + 0.25*1500
PLAYOFF_MULT = 1.10     # leichte Erhöhung in Playoffs
MARGIN_C = 10.0         # für Margin-of-Victory (ln(1+pdiff/C))

def expected_score(r_a, r_b):
    return 1.0 / (1.0 + 10 ** (-(r_a - r_b) / 400.0))

def margin_multiplier(pdiff):
    # sanftes Scaling, capped
    m = math.log(1 + abs(pdiff) / MARGIN_C + 1e-9, 2)
    return max(0.5, min(2.0, m))  # 0.5..2.0

def normalize_name(s):
    return (s or "").strip()

def read_weekly_csv(path):
    """
    Erwartete Spalten (Beispiel aus deiner Datei):
    Owner,Total,Opponent,Opponent Total
    Wir nehmen nur 1 Eintrag je Matchup, daher 'Owner' < 'Opponent' als Filter.
    """
    games = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # robust gegen Header-Varianten
        cols = {c.lower(): c for c in reader.fieldnames or []}
        def col(name):  # tolerant auf Leerzeichen / Case
            for k,v in cols.items():
                if k.replace(" ", "") == name.replace(" ", "").lower():
                    return v
            return name

        owner_col = col("Owner")
        opp_col   = col("Opponent")
        tot_col   = col("Total")
        opt_col   = col("Opponent Total")

        for row in reader:
            o = normalize_name(row.get(owner_col, ""))
            a = normalize_name(row.get(opp_col, ""))
            try:
                op = float(str(row.get(tot_col, "0")).replace(",", "."))
            except: op = 0.0
            try:
                ap = float(str(row.get(opt_col, "0")).replace(",", "."))
            except: ap = 0.0
            # nur ein Record je Paar
            key_owner_first = o <= a
            games.append((o, a, op, ap, key_owner_first))
    # Filter duplikate: behalte nur die, bei denen owner<=opponent war
    uniq = []
    seen = set()
    for o,a,op,ap,ok in games:
        if not o or not a: 
            continue
        pair = tuple(sorted([o,a]))
        if pair in seen:
            continue
        if ok:
            uniq.append((o,a,op,ap))
            seen.add(pair)
    return uniq

def iter_year_weeks():
    years = []
    for ydir in glob.glob(os.path.join(WEEKLY_DIR, "*")):
        if os.path.isdir(ydir) and os.path.basename(ydir).isdigit():
            years.append(int(os.path.basename(ydir)))
    years.sort()
    for y in years:
        week_files = []
        for f in glob.glob(os.path.join(WEEKLY_DIR, str(y), "*.csv")):
            base = os.path.splitext(os.path.basename(f))[0]
            if base.isdigit():
                week_files.append((int(base), f))
        week_files.sort(key=lambda x: x[0])
        if not week_files:
            continue
        yield y, week_files

def main():
    os.makedirs(ELO_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(ELO_JSON), exist_ok=True)

    ratings = {}                 # aktuelle Elo pro Team
    last_seen_in_prev_season = set()
    out_rows = []                # für TSV/JSON

    first_season = None
    for season, week_files in iter_year_weeks():
        if first_season is None:
            first_season = season

        # Season-Reset: Regression to mean
        if season != first_season:
            for t in list(ratings.keys()):
                ratings[t] = MEAN_REGRESSION * ratings[t] + (1.0 - MEAN_REGRESSION) * BASE_RATING

        # Erkennen wir Playoffs über Wochenzahl? 
        # Faustregel: regulär 1–14, alles >14 ist Playoff
        for week, fpath in week_files:
            is_playoff = week > 14
            games = read_weekly_csv(fpath)

            # Stelle sicher, dass alle Teams ein Rating haben
            teams_in_week = set()
            for o,a,_,_ in games:
                teams_in_week.add(o)
                teams_in_week.add(a)
            for t in teams_in_week:
                ratings.setdefault(t, BASE_RATING)

            # Elo Updates
            for o,a,op,ap in games:
                ra = ratings[o]
                rb = ratings[a]

                ea = expected_score(ra, rb)
                eb = 1.0 - ea
                if op == ap: 
                    sa, sb = 0.5, 0.5
                    pdiff = 0.0
                else:
                    sa = 1.0 if op > ap else 0.0
                    sb = 1.0 - sa
                    pdiff = abs(op - ap)

                k = K_BASE * (PLAYOFF_MULT if is_playoff else 1.0) * margin_multiplier(pdiff)
                ra_new = ra + k * (sa - ea)
                rb_new = rb + k * (sb - eb)
                ratings[o] = ra_new
                ratings[a] = rb_new

            # Snapshot nach Woche schreiben
            for t in sorted(teams_in_week):
                out_rows.append({
                    "Season": season,
                    "Week": week,
                    "Team": t,
                    "Elo": round(ratings[t], 2),
                    "IsPlayoff": int(is_playoff)
                })

    # TSV
    with open(ELO_TSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["Season","Week","Team","Elo","IsPlayoff"])
        for r in out_rows:
            w.writerow([r["Season"], r["Week"], r["Team"], f'{r["Elo"]:.2f}', r["IsPlayoff"]])

    # JSON (für Frontend)
    with open(ELO_JSON, "w", encoding="utf-8") as f:
        json.dump(out_rows, f, ensure_ascii=False)

    print(f"✅ Elo TSV:   {ELO_TSV}")
    print(f"✅ Elo JSON:  {ELO_JSON}")
    print(f"Teams insgesamt: {len({r['Team'] for r in out_rows})}")

if __name__ == "__main__":
    main()
