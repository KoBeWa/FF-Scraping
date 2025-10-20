#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from pathlib import Path
import pandas as pd

INPUT_DIR = Path("output/3082897-history-standings")
OUTPUT_FILE = INPUT_DIR / "aggregated_playoffs.tsv"

# ---------- Helpers ----------
def to_float(x):
    """Robust für EN/DE-Formate: '1,455.70' / '1.455,70' / '1455.7' / '1455'."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return 0.0
    s = str(x).strip().replace('"', '').replace("'", "").replace(" ", "")
    if s == "":
        return 0.0
    # DE-Format: 1.234,56 -> 1234.56
    if re.match(r"^\d{1,3}(\.\d{3})+,\d+$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        # EN-Format: 1,234.56 -> 1234.56
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0

def to_int(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return 0
    s = str(x).strip()
    if s == "":
        return 0
    m = re.search(r"\d+", s)
    return int(m.group()) if m else 0

# ---------- Einlesen aller playoffs-YYYY.tsv ----------
rows = []
playoff_files = sorted(INPUT_DIR.glob("playoffs-*.tsv"))
year_re = re.compile(r"^playoffs-(\d{4})\.tsv$")

if not playoff_files:
    raise SystemExit(f"No playoff TSV files found under {INPUT_DIR}/playoffs-YYYY.tsv")

for f in playoff_files:
    m = year_re.match(f.name)
    if not m:
        print(f"Skipping {f} (unexpected filename).")
        continue
    season = int(m.group(1))

    df = pd.read_csv(f, sep="\t", dtype=str, keep_default_na=False)

    # Spalten (case-insensitive) suchen
    colmap = {c.lower(): c for c in df.columns}
    def get(*candidates):
        for cand in candidates:
            real = colmap.get(cand.lower())
            if real:
                return real
        return None

    c_manager = get("ManagerName", "Manager", "Owner")
    c_seed = get("Seed")
    c_prank = get("PlayoffRank", "Playoff Rank")
    c_w15 = get("Week15Pts", "Week15", "Week 15", "Week 15 Pts")
    c_w16 = get("Week16Pts", "Week16", "Week 16", "Week 16 Pts")

    missing = [n for n, real in [
        ("ManagerName", c_manager),
        ("Seed", c_seed),
        ("PlayoffRank", c_prank),
        ("Week15Pts", c_w15),
        ("Week16Pts", c_w16),
    ] if real is None]
    if missing:
        print(f"Skipping {f} — missing columns: {missing}")
        continue

    # Normieren
    df_norm = pd.DataFrame({
        "Season": season,
        "ManagerName": df[c_manager].astype(str).str.strip(),
        "Seed": df[c_seed].astype(str).str.strip().map(to_int),
        "PlayoffRank": pd.to_numeric(df[c_prank].astype(str).str.strip(), errors="coerce"),
        "Week15Pts": df[c_w15].astype(str).str.strip().map(to_float),
        "Week16Pts": df[c_w16].astype(str).str.strip().map(to_float),
    })

    # Erwartete Seeds prüfen (1..8)
    # (Wir erzwingen sie nicht hart, aber Warnung falls abweichend)
    seeds_set = set(df_norm["Seed"].dropna().astype(int).tolist())
    if not seeds_set.issubset({1,2,3,4,5,6,7,8}):
        print(f"Warning {f}: unexpected seeds present: {sorted(seeds_set)}")

    # Week-15 Paarungen gem. Vorgabe:
    # 1 vs 4, 2 vs 3, 5 vs 8, 6 vs 7
    pairings_w15 = [(1,4), (2,3), (5,8), (6,7)]

    # Map Seed -> Index (Zeile) für diese Saison
    df_norm = df_norm.set_index("Seed", drop=False)
    missing_seeds = [a for pair in pairings_w15 for a in pair if a not in df_norm.index]
    if missing_seeds:
        print(f"Warning {f}: missing seeds for W15 pairing: {missing_seeds}")

    # Gegnerpunkte / Win/Loss für Week 15 berechnen
    w15_opp_pts = {}
    w15_win = {}
    for a, b in pairings_w15:
        if a in df_norm.index and b in df_norm.index:
            pa = df_norm.loc[a, "Week15Pts"]
            pb = df_norm.loc[b, "Week15Pts"]
            w15_opp_pts[a] = pb
            w15_opp_pts[b] = pa
            w15_win[a] = 1 if pa > pb else 0
            w15_win[b] = 1 if pb > pa else 0

    # Week-16 Paarungen:
    # Gewinner-vs-Gewinner, Verlierer-vs-Verlierer innerhalb der oberen Klammer (1/4 & 2/3)
    # und innerhalb der unteren Klammer (5/8 & 6/7).
    def w16_pairs(block_pairs):
        winners = []
        losers = []
        for a, b in block_pairs:
            if a in df_norm.index and b in df_norm.index:
                pa = df_norm.loc[a, "Week15Pts"]
                pb = df_norm.loc[b, "Week15Pts"]
                if pa > pb:
                    winners.append(a); losers.append(b)
                else:
                    winners.append(b); losers.append(a)
        # Gewinner untereinander, Verlierer untereinander
        pairs = []
        if len(winners) == 2:
            pairs.append((winners[0], winners[1]))
        if len(losers) == 2:
            pairs.append((losers[0], losers[1]))
        return pairs

    w16_pairs_top = w16_pairs([(1,4), (2,3)])   # Championship & 3rd place
    w16_pairs_bot = w16_pairs([(5,8), (6,7)])   # 5th/7th place bracket
    all_w16_pairs = w16_pairs_top + w16_pairs_bot

    w16_opp_pts = {}
    w16_win = {}
    for a, b in all_w16_pairs:
        if a in df_norm.index and b in df_norm.index:
            pa = df_norm.loc[a, "Week16Pts"]
            pb = df_norm.loc[b, "Week16Pts"]
            w16_opp_pts[a] = pb
            w16_opp_pts[b] = pa
            w16_win[a] = 1 if pa > pb else 0
            w16_win[b] = 1 if pb > pa else 0

    # Zeilen zurück auf normaler Index
    df_norm = df_norm.reset_index(drop=True)

    # Pro Team/Saison Stat-Zeile erzeugen
    df_norm["PF"] = df_norm["Week15Pts"].fillna(0) + df_norm["Week16Pts"].fillna(0)
    df_norm["PA"] = df_norm["Seed"].map(w15_opp_pts).fillna(0) + df_norm["Seed"].map(w16_opp_pts).fillna(0)
    df_norm["W15Win"] = df_norm["Seed"].map(w15_win).fillna(0).astype(int)
    df_norm["W16Win"] = df_norm["Seed"].map(w16_win).fillna(0).astype(int)
    df_norm["Wins"] = df_norm["W15Win"] + df_norm["W16Win"]
    df_norm["Losses"] = 2 - df_norm["Wins"]
    df_norm["Championships"] = (df_norm["PlayoffRank"] == 1).astype(int)

    rows.append(df_norm)

# --- Sammeln & Aggregieren ---
if not rows:
    raise SystemExit("No playoff rows parsed.")
all_playoffs = pd.concat(rows, ignore_index=True)

grouped = all_playoffs.groupby("ManagerName", dropna=False)

agg = grouped.agg(
    PointsFor=pd.NamedAgg(column="PF", aggfunc="sum"),
    PointsAgainst=pd.NamedAgg(column="PA", aggfunc="sum"),
    Wins=pd.NamedAgg(column="Wins", aggfunc="sum"),
    Losses=pd.NamedAgg(column="Losses", aggfunc="sum"),
    Championships=pd.NamedAgg(column="Championships", aggfunc="sum"),
    W15Wins=pd.NamedAgg(column="W15Win", aggfunc="sum"),
    W16Wins=pd.NamedAgg(column="W16Win", aggfunc="sum"),
    W15Apps=pd.NamedAgg(column="W15Win", aggfunc="count"),
    W16Apps=pd.NamedAgg(column="W16Win", aggfunc="count"),
    AvgSeed=pd.NamedAgg(column="Seed", aggfunc="mean"),
    AvgPlayoffRank=pd.NamedAgg(column="PlayoffRank", aggfunc="mean"),
    Seasons=pd.NamedAgg(column="Season", aggfunc="nunique"),
)

# Prozente
agg["Week15WinPct"] = (agg["W15Wins"] / agg["W15Apps"]).round(3).fillna(0)
agg["Week16WinPct"] = (agg["W16Wins"] / agg["W16Apps"]).round(3).fillna(0)

# Aufräumen / Reihenfolge
result = agg.drop(columns=["W15Wins", "W16Wins", "W15Apps", "W16Apps"]).reset_index()

# Typen/Format
for c in ["PointsFor", "PointsAgainst"]:
    result[c] = result[c].round(2)
for c in ["Wins", "Losses", "Championships", "Seasons"]:
    result[c] = result[c].astype(int)
result["AvgSeed"] = result["AvgSeed"].round(2)
result["AvgPlayoffRank"] = result["AvgPlayoffRank"].round(2)

# Spaltenreihenfolge wie gewünscht
result = result[[
    "ManagerName",
    "PointsFor",
    "PointsAgainst",
    "Wins",
    "Losses",
    "Championships",
    "Week15WinPct",
    "Week16WinPct",
    "AvgSeed",
    "AvgPlayoffRank",
    "Seasons",
]]

# Sortierung: zuerst Championships, dann Week16WinPct, dann PointsFor
result = result.sort_values(
    by=["Championships", "Week16WinPct", "PointsFor"],
    ascending=[False, False, False]
)

# Export
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
result.to_csv(OUTPUT_FILE, sep="\t", index=False)

print(f"Wrote {OUTPUT_FILE} with {len(result)} rows.")
