import csv
import os
from utils import get_number_of_owners
from constants import leagueID, standings_directory

# Aggregates all yearly standings into a single all-time CSV file

aggregated_data = {}

for filename in os.listdir(standings_directory):
    if not filename.endswith(".csv"):
        continue

    filepath = os.path.join(standings_directory, filename)
    season = filename[:-4]

    with open(filepath, 'r', newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        num_owners = get_number_of_owners(leagueID, season)

        for row in reader:
            manager = row.get("ManagerName", "").strip()
            if not manager:
                continue

            # Initialisieren, wenn neuer Manager
            if manager not in aggregated_data:
                aggregated_data[manager] = {
                    "PointsFor": 0.0,
                    "PointsAgainst": 0.0,
                    "Moves": 0.0,
                    "Trades": 0.0,
                    "Wins": 0,
                    "Losses": 0,
                    "Ties": 0,
                    "Championships": 0,
                    "Playoffs": 0,
                    "Sackos": 0,
                    "DraftPosition_sum": 0.0,
                    "Seasons": 0
                }

            data = aggregated_data[manager]
            data["Seasons"] += 1

            # Zahlen sicher parsen
            def to_float(x): 
                try: return float(x.replace(",", "").strip())
                except: return 0.0

            # Punkte, Moves etc.
            data["PointsFor"] += to_float(row.get("PointsFor", 0))
            data["PointsAgainst"] += to_float(row.get("PointsAgainst", 0))
            data["Moves"] += to_float(row.get("Moves", 0))
            data["Trades"] += to_float(row.get("Trades", 0))
            data["DraftPosition_sum"] += to_float(row.get("DraftPosition", 0))

            # Record z. B. "8-5-0"
            record = row.get("Record", "")
            if record:
                parts = record.split("-")
                if len(parts) >= 2:
                    data["Wins"] += int(parts[0])
                    data["Losses"] += int(parts[1])
                    if len(parts) == 3:
                        data["Ties"] += int(parts[2])

            # Playoff-Auswertung
            try:
                playoff_rank = int(row.get("PlayoffRank", 0))
                if playoff_rank == 1:
                    data["Playoffs"] += 1
                    data["Championships"] += 1
                elif playoff_rank == num_owners:
                    data["Sackos"] += 1
                elif playoff_rank <= num_owners / 2:
                    data["Playoffs"] += 1
            except:
                pass


# CSV-Ausgabe
output_path = "./output/aggregated_standings_data.csv"
with open(output_path, "w", newline='', encoding='utf-8') as f:
    fieldnames = [
        "ManagerName",
        "PointsFor", "PointsAgainst", "Moves", "Trades",
        "Wins", "Losses", "Ties",
        "Championships", "Playoffs", "Sackos",
        "DraftPosition", "Seasons"
    ]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()

    for manager, d in aggregated_data.items():
        row = {
            "ManagerName": manager,
            "PointsFor": round(d["PointsFor"], 2),
            "PointsAgainst": round(d["PointsAgainst"], 2),
            "Moves": int(d["Moves"]),
            "Trades": int(d["Trades"]),
            "Wins": d["Wins"],
            "Losses": d["Losses"],
            "Ties": d["Ties"],
            "Championships": d["Championships"],
            "Playoffs": d["Playoffs"],
            "Sackos": d["Sackos"],
            "DraftPosition": round(d["DraftPosition_sum"] / d["Seasons"], 1) if d["Seasons"] > 0 else 0,
            "Seasons": d["Seasons"]
        }
        writer.writerow(row)

print(f"✅ Aggregated standings written to {output_path}")
