# scrapeSleeperStandings.py
import csv, os
from collections import defaultdict
from sleeper_api import get_league, get_league_users, get_league_rosters, get_matchups

LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID", "").strip()
SEASON     = int(os.getenv("SEASON", "2025"))
OUT_DIR    = "./output"

def main():
    os.makedirs(f"{OUT_DIR}/{SEASON}", exist_ok=True)

    league = get_league(LEAGUE_ID)
    # Regular-Season-Länge (Standard 14, kann variieren)
    reg_weeks = league.get("settings", {}).get("playoff_week_start", 15) - 1

    users   = get_league_users(LEAGUE_ID)
    rosters = get_league_rosters(LEAGUE_ID)

    # Maps: roster_id -> owner_id ; owner_id -> display_name
    rid_to_owner = {r["roster_id"]: r.get("owner_id") for r in rosters}
    owner_to_name = {u["user_id"]: (u.get("metadata", {}).get("team_name") or u.get("display_name") or "Unknown") for u in users}

    # Stats-Container
    W = defaultdict(int); L = defaultdict(int); T = defaultdict(int)
    PF = defaultdict(float); PA = defaultdict(float)

    # Pro Woche Matchups ziehen und Standings aufbauen
    for week in range(1, reg_weeks + 1):
        week_data = get_matchups(LEAGUE_ID, week)  # Liste von Team-Objekten; Paarung via matchup_id
        # Gruppieren nach matchup_id
        by_mid = defaultdict(list)
        for t in week_data:
            by_mid[t.get("matchup_id")].append(t)

        for mid, teams in by_mid.items():
            if len(teams) != 2:
                # Bye/Median/Custom — hier ggf. überspringen oder Speziallogik
                continue
            a, b = teams
            a_pts, b_pts = float(a.get("points", 0)), float(b.get("points", 0))
            a_name = owner_to_name.get(rid_to_owner.get(a["roster_id"]), f"Roster {a['roster_id']}")
            b_name = owner_to_name.get(rid_to_owner.get(b["roster_id"]), f"Roster {b['roster_id']}")

            PF[a_name] += a_pts; PA[a_name] += b_pts
            PF[b_name] += b_pts; PA[b_name] += a_pts

            if a_pts > b_pts:
                W[a_name] += 1; L[b_name] += 1
            elif b_pts > a_pts:
                W[b_name] += 1; L[a_name] += 1
            else:
                T[a_name] += 1; T[b_name] += 1

    # CSV schreiben (pro Saison)
    out = f"{OUT_DIR}/{SEASON}/standings_sleeper_{SEASON}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Team","W","L","T","PF","PA","Diff"])
        teams = sorted(PF.keys(), key=lambda n: (W[n], PF[n]), reverse=True)
        for name in teams:
            w.writerow([name, W[name], L[name], T[name], round(PF[name],2), round(PA[name],2), round(PF[name]-PA[name],2)])

    print(f"✓ Standings geschrieben: {out}")

if __name__ == "__main__":
    main()
