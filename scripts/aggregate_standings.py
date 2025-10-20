import pandas as pd
from pathlib import Path
import re

INPUT_DIR = Path("output/3082897-history-standings")
OUTPUT_FILE = INPUT_DIR / "aggregated_standings.tsv"

# ------- Helpers -------
def to_float(x):
    """Convert strings like '1,448.58' or '1448.58' to float. Empty -> 0.0"""
    if pd.isna(x):
        return 0.0
    s = str(x).strip().replace('"', '').replace("'", "")
    # remove thousands separators
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0

def to_int(x):
    if pd.isna(x) or str(x).strip() == "":
        return 0
    try:
        return int(float(str(x).replace(",", "").strip()))
    except ValueError:
        return 0

def playoff_bucket_counts(sr):
    """Return dict with counts for the various playoff buckets from a numeric Series."""
    s = pd.to_numeric(sr, errors="coerce")
    return {
        "Championships": (s == 1).sum(),
        "Playoffs": ((s >= 1) & (s <= 4)).sum(),
        "Finals": ((s >= 1) & (s <= 2)).sum(),
        "Toiletbowls": ((s >= 7) & (s <= 8)).sum(),
        "Sackos": (s == 8).sum(),
    }

def parse_record(rec):
    """Parse 'W-L-T' like '11-3-0' -> (W,L,T)."""
    if pd.isna(rec):
        return (0, 0, 0)
    parts = str(rec).strip().split("-")
    if len(parts) == 3:
        try:
            return (int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            return (0, 0, 0)
    return (0, 0, 0)

# ------- Load all seasons -------
rows = []
tsv_files = sorted(INPUT_DIR.glob("*.tsv"))
season_re = re.compile(r"(\d{4})\.tsv$")

if not tsv_files:
    raise SystemExit(f"No TSV files found in {INPUT_DIR}")

for f in tsv_files:
    m = season_re.search(str(f))
    season = int(m.group(1)) if m else None
    # Read as raw strings to normalize manually
    df = pd.read_csv(f, sep="\t", dtype=str, keep_default_na=False)

    # Normalize expected columns (some exports may vary in capitalization)
    colmap = {c.lower(): c for c in df.columns}
    def get(colname):
        # returns actual column name from case-insensitive lookup or None
        return colmap.get(colname.lower())

    # Required / commonly present columns
    c_manager = get("ManagerName") or get("Manager") or get("Owner") or get("OwnerName")
    c_points_for = get("PointsFor")
    c_points_against = get("PointsAgainst")
    c_moves = get("Moves")
    c_trades = get("Trades")
    c_record = get("Record")
    c_playoff = get("PlayoffRank") or get("Playoff Rank") or get("Playoff")
    c_draftpos = get("DraftPosition") or get("Draft Position")

    # Sanity checks
    missing = [("ManagerName", c_manager), ("PointsFor", c_points_for), ("PointsAgainst", c_points_against)]
    missing_cols = [name for name, real in missing if real is None]
    if missing_cols:
        raise SystemExit(f"Missing required columns {missing_cols} in file {f}")

    tmp = pd.DataFrame({
        "Season": season,
        "ManagerName": df[c_manager].astype(str).str.strip(),
        "PointsFor": df[c_points_for].map(to_float),
        "PointsAgainst": df[c_points_against].map(to_float),
        "Moves": df[c_moves].map(to_int) if c_moves else 0,
        "Trades": df[c_trades].map(to_int) if c_trades else 0,
        "Record": df[c_record] if c_record else "",
        "PlayoffRank": pd.to_numeric(df[c_playoff], errors="coerce") if c_playoff else pd.NA,
        "DraftPosition": pd.to_numeric(df[c_draftpos], errors="coerce") if c_draftpos else pd.NA,
    })

    # Wins/Losses/Ties from Record
    wlt = tmp["Record"].apply(parse_record)
    tmp[["Wins", "Losses", "Ties"]] = pd.DataFrame(wlt.tolist(), index=tmp.index)

    rows.append(tmp)

all_seasons = pd.concat(rows, ignore_index=True)

# ------- Aggregate -------
grouped = all_seasons.groupby("ManagerName", dropna=False)

agg_num = grouped[["PointsFor", "PointsAgainst", "Moves", "Trades", "Wins", "Losses", "Ties"]].sum().round(2)

# Average Draft Position (ignore NaN)
avg_draft = grouped["DraftPosition"].mean().round(2).rename("DraftPosition")

# Seasons = number of distinct seasons a manager appears in
season_counts = grouped["Season"].nunique().rename("Seasons")

# Playoff buckets
playoff_df = grouped["PlayoffRank"].apply(lambda s: pd.Series(playoff_bucket_counts(s)))

# Put it all together
result = (
    agg_num
    .join(playoff_df)
    .join(avg_draft)
    .join(season_counts)
    .reset_index()
)

# Column order
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
# Ensure all columns exist (in case some buckets didn't appear in data)
for c in cols:
    if c not in result.columns:
        result[c] = 0

result = result[cols]

# Sort (feel free to tweak: by Championships, then Wins, then PointsFor)
result = result.sort_values(by=["Championships", "Wins", "PointsFor"], ascending=[False, False, False])

# Save
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
result.to_csv(OUTPUT_FILE, sep="\t", index=False)
print(f"Wrote {OUTPUT_FILE} with {len(result)} rows.")
