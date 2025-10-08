import pandas as pd
from pathlib import Path

# Pfad zu deinen Saison-TSV-Dateien
DIR = Path("output/3082897-history-standings")
files = sorted(DIR.glob("*.tsv"))

dfs = []
for f in files:
    df = pd.read_csv(f, sep="\t")
    df["Season"] = f.stem  # Jahr aus Dateiname
    dfs.append(df)

all_data = pd.concat(dfs, ignore_index=True)

# Record aufsplitten
rec_split = all_data["Record"].str.split("-", expand=True).astype(int)
all_data["Wins"] = rec_split[0]
all_data["Losses"] = rec_split[1]
all_data["Ties"] = rec_split[2]

# Aggregation
agg = (
    all_data.groupby("ManagerName")
    .agg(
        PointsFor=("PointsFor", lambda x: x.replace(",", "", regex=True).astype(float).sum()),
        PointsAgainst=("PointsAgainst", lambda x: x.replace(",", "", regex=True).astype(float).sum()),
        Moves=("Moves", "sum"),
        Trades=("Trades", "sum"),
        Wins=("Wins", "sum"),
        Losses=("Losses", "sum"),
        Ties=("Ties", "sum"),
        Championships=("PlayoffRank", lambda x: (x == 1).sum()),
        Playoffs=("PlayoffRank", lambda x: (x <= 4).sum()),
        Sackos=("PlayoffRank", lambda x: (x == 8).sum()),
        DraftPosition=("DraftPosition", "mean"),
        Seasons=("Season", "count"),
    )
    .reset_index()
)

# Optional: runde DraftPosition
agg["DraftPosition"] = agg["DraftPosition"].round(1)

# Sortieren z. B. nach Wins oder Championships
agg = agg.sort_values(["Championships", "Wins"], ascending=[False, False])

# Speichern als TSV
out_file = DIR / "aggregated_standings.tsv"
agg.to_csv(out_file, sep="\t", index=False)

print(f"✅ Aggregated standings saved to {out_file}")
