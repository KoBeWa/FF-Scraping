#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from pathlib import Path

import pandas as pd

INPUT_DIR = Path("output/3082897-history-standings")
OUTPUT_FILE = INPUT_DIR / "aggregated_standings.tsv"


# ---------- Helpers ----------
def to_float(x):
    """
    Robuster Parser für Zahlen wie:
    - '1,455.70' (EN tausender-Komma, Dezimalpunkt)
    - '1.455,70' (DE tausender-Punkt, Dezimalkomma)
    - '1455.70' / '1455,70' / '1455'
    Leere / ungültige Werte -> 0.0
    """
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return 0.0
    s = str(x).strip().replace('"', '').replace("'", "").replace(" ", "")
    if s == "":
        return 0.0
    # DE-Format: 1.234,56  (Punkt = Tausender, Komma = Dezimal)
    if re.match(r"^\d{1,3}(\.\d{3})+,\d+$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        # Sonst: entferne Tausender-Kommas, halte Dezimalpunkt
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def to_int(x):
    """Zieht die erste Ganzzahl aus einem String (z. B. '8', ' 8 ', '8th'). Leer -> 0."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return 0
    s = str(x).strip()
    if s == "":
        return 0
    m = re.search(r"\d+", s)
    return int(m.group()) if m else 0


def parse_record(rec: str):
    """
    Extrahiert W-L-T aus Record-Strings (z. B. '11-3-0', '11–3–0 (2nd)').
    Wenn kein Tie vorhanden ist, wird T=0 angenommen.
    Ungültig/leer -> (0,0,0)
    """
    if pd.isna(rec):
        return (0, 0, 0)
    nums = re.findall(r"\d+", str(rec))
    if len(nums) >= 3:
        return (int(nums[0]), int(nums[1]), int(nums[2]))
    if len(nums) == 2:
        return (int(nums[0]), int(nums[1]), 0)
    return (0, 0, 0)


# ---------- Load all seasons (YYYY.tsv only) ----------
rows = []
tsv_files = sorted(INPUT_DIR.glob("[0-9][0-9][0-9][0-9].tsv"))
if not tsv_files:
    raise SystemExit(f"No TSV files found matching YYYY.tsv under {INPUT_DIR}")

for f in tsv_files:
    season = int(f.stem)  # stem ist '2015' etc.

    # Einlesen als Strings, damit wir selber normalisieren
    df = pd.read_csv(f, sep="\t", dtype=str, keep_default_na=False)

    # Case-insensitive Spaltenzuordnung
    colmap = {c.lower(): c for c in df.columns}

    def get(*candidates):
        """Hole die erste existierende Spalte aus Kandidatennamen (case-insensitive)."""
        for cand in candidates:
            real = colmap.get(cand.lower())
            if real:
                return real
        return None

    c_manager = get("ManagerName", "Manager", "Owner", "OwnerName")
    c_points_for = get("PointsFor", "PF", "Points For")
    c_points_against = get("PointsAgainst", "PA", "Points Against")
    c_moves = get("Moves")
    c_trades = get("Trades")
    c_record = get("Record")
    c_playoff = get("PlayoffRank", "Playoff Rank", "Playoff")
    c_draftpos = get("DraftPosition", "Draft Position")

    # Pflichtspalten prüfen – wenn PF/PA/Manager fehlen, Datei überspringen
    missing = [n for n, real in [
        ("ManagerName", c_manager),
        ("PointsFor", c_points_for),
        ("PointsAgainst", c_points_against),
    ] if real is None]
    if missing:
        print(f"Skipping {f} — missing required columns: {missing}")
        continue

    def col_stripped(colname):
        return df[colname].astype(str).str.strip()

    tmp = pd.DataFrame({
        "Season": season,
        "ManagerName": col_stripped(c_manager),
        "PointsFor": col_stripped(c_points_for).map(to_float),
        "PointsAgainst": col_stripped(c_points_against).map(to_float),
        "Moves": col_stripped(c_moves).map(to_int) if c_moves else 0,
        "Trades": col_stripped(c_trades).map(to_int) if c_trades else 0,
        "Record": col_stripped(c_record) if c_record else "",
        "PlayoffRank": pd.to_numeric(col_stripped(c_playoff), errors="coerce") if c_playoff else pd.Series([pd.NA]*len(df)),
        "DraftPosition": pd.to_numeric(col_stripped(c_draftpos), errors="coerce") if c_draftpos else pd.NA,
    })

    # Record -> Wins/Losses/Ties
    wlt = tmp["Record"].apply(parse_record)
    tmp[["Wins", "Losses", "Ties"]] = pd.DataFrame(wlt.tolist(), index=tmp.index)

    rows.append(tmp)

if not rows:
    raise SystemExit("No valid season rows parsed (after skipping files with missing required columns).")

all_seasons = pd.concat(rows, ignore_index=True)

# ---------- Aggregate ----------
grouped = all_seasons.groupby("ManagerName", dropna=False)

agg_num = grouped[["PointsFor", "PointsAgainst", "Moves", "Trades", "Wins", "Losses", "Ties"]].sum().round(2)
avg_draft = grouped["DraftPosition"].mean().round(2).rename("DraftPosition")
season_counts = grouped["Season"].nunique().rename("Seasons")

# Playoff-Buckets ohne MultiIndex-Duplikate
playoff_df = grouped["PlayoffRank"].agg(
    Championships=lambda s: (s == 1).sum(),
    Playoffs=lambda s: ((s >= 1) & (s <= 4)).sum(),
    Finals=lambda s: ((s >= 1) & (s <= 2)).sum(),
    Toiletbowls=lambda s: ((s >= 7) & (s <= 8)).sum(),
    Sackos=lambda s: (s == 8).sum(),
)

result = (
    agg_num
    .join(playoff_df)
    .join(avg_draft)
    .join(season_counts)
    .reset_index()
)

# Fehlende Spalten ergänzen + Typen bereinigen
int_cols = [
    "Moves", "Trades", "Wins", "Losses", "Ties",
    "Championships", "Playoffs", "Finals", "Toiletbowls", "Sackos", "Seasons"
]
for c in int_cols:
    if c not in result.columns:
        result[c] = 0
    result[c] = pd.to_numeric(result[c], errors="coerce").fillna(0).astype(int)

if "DraftPosition" in result.columns:
    result["DraftPosition"] = pd.to_numeric(result["DraftPosition"], errors="coerce").round(2)

# Spaltenreihenfolge & Sortierung
cols = [
    "ManagerName",
    "PointsFor",
    "PointsAgainst",
    "Moves",
    "Trades",
    "Wins",
    "Losses",
    "Ties",
    "Championships",
    "Playoffs",
    "Finals",
    "Toiletbowls",
    "Sackos",
    "DraftPosition",
    "Seasons",
]
for c in cols:
    if c not in result.columns:
        result[c] = 0

result = result[cols].sort_values(by=["Championships", "Wins", "PointsFor"], ascending=[False, False, False])

# Export
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
result.to_csv(OUTPUT_FILE, sep="\t", index=False)

print(f"Wrote {OUTPUT_FILE} with {len(result)} rows.")
