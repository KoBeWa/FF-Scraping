import csv
import os
from utils import get_number_of_owners
from constants import leagueID, standings_directory

aggregated_data = {}

for filename in os.listdir(standings_directory):
    if not (filename.endswith(".csv") or filename.endswith(".tsv")):
        continue

    filepath = os.path.join(standings_directory, filename)
    season = filename[:-4]

    delimiter = '\t' if filename.endswith(".tsv") else ','

    with open(filepath, 'r', newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file, delimiter=delimiter)
        num_owners = get_number_of_owners(leagueID, season)

        for row in reader:
            manager = str(row.get("ManagerName", "")).strip()
            if not manager:
                continue

            if manager not in aggregated_data:
                aggregated_data[manager] = {
                    "PointsFor": 0.0,
                    "PointsAgainst": 0.0,
                    "Moves": 0,
                    "Trades": 0,
                    "Wins": 0,
                    "Losses": 0,
                    "Ties": 0,
                    "Championships": 0,
                    "Playoffs": 0,
                    "Sackos": 0,
                    "DraftPosition_sum": 0.0,
                    "ValidDrafts": 0,
                    "Seasons": 0
                }

            d = aggregated_data[manager]
            d["Seasons"] += 1

            def to_float(x):
                try:
                    x = str(x).replace(",", "").replace("–", "-").strip()
                    return float(x) if x not in ["", "None", "nan"] else 0.0
                except:
                    return 0.0

            def to_int(x):
                try:
                    return int(float(str(x).strip()))
                except:
                    return 0

            d["PointsFor"] += to_float(row.get("PointsFor", 0))
            d["PointsAgainst"] += to_float(row.get("PointsAgainst", 0))
            d["Moves"] += to_int(row.get("Moves", 0))
            d["Trades"] += to_int(row.get("Trades", 0))

            draft = to_float(row.get("DraftPosition", 0))
            if draft > 0:
                d["DraftPosition_sum"] += draft
                d["ValidDrafts"] += 1

            record = str(row.get("Record", "")).strip()
            if record:
                parts = record.split("-")
                if len(parts) >= 2:
                    d["Wins"] += int(parts[0])
                    d["Losses"] += int(parts[1])
                    if len(parts) == 3:
                        d["Ties"] += int(parts[2])

            try:
                playoff_rank = int(float(row.get("PlayoffRank", 0)))
                if playoff_rank == 1:
                    d["Championships"] += 1
                    d["Playoffs"] += 1
                elif playoff_rank <= num_owners / 2:
                    d["Playoffs"] += 1
                elif playoff_rank == num_owners:
                    d["Sackos"] += 1
            except:
                pass

output_path = os.path.join(standings_directory, "..", "aggregated_standings.csv")
os.makedirs(os.path.dirname(output_path), exist_ok=True)

with open(output_path, "w", newline='', encoding="utf-8") as f:
    fieldnames = [
        "ManagerName", "Seasons", "Wins", "Losses", "Ties",
        "Championships", "Playoffs", "Sackos",
        "PointsFor", "PointsAgainst",
        "Moves", "Trades", "DraftPosition"
    ]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()

    for manager, d in sorted(aggregated_data.items(), key=lambda x: (-x[1]["Wins"], -x[1]["PointsFor"])):
        valid_drafts = d["ValidDrafts"] or d["Seasons"]
        avg_draft = round(d["DraftPosition_sum"] / valid_drafts, 1)
        writer.writerow({
            "ManagerName": manager,
            "Seasons": d["Seasons"],
            "Wins": d["Wins"],
            "Losses": d["Losses"],
            "Ties": d["Ties"],
            "Championships": d["Championships"],
            "Playoffs": d["Playoffs"],
            "Sackos": d["Sackos"],
            "PointsFor": round(d["PointsFor"], 2),
            "PointsAgainst": round(d["PointsAgainst"], 2),
            "Moves": d["Moves"],
            "Trades": d["Trades"],
            "DraftPosition": avg_draft
        })

print(f"✅ Aggregated standings written to {output_path}")
