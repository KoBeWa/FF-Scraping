# scrapeNFLDraftboards.py
import os
import csv
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Wir benutzen dieselbe Session-Quelle wie deine anderen Scraper
# (cookieString.get_session liest NFL_COOKIE aus Secret/ENV oder data/nfl_cookie.txt)
from cookieString import get_session

OUT_DIR = Path("output/drafts")
DBG_DIR = Path("debug/drafts")
OUT_DIR.mkdir(parents=True, exist_ok=True)
DBG_DIR.mkdir(parents=True, exist_ok=True)

LEAGUE_ID = os.getenv("LEAGUE_ID", "").strip()
START = int(os.getenv("LEAGUE_START_YEAR", "2015"))
END   = int(os.getenv("LEAGUE_END_YEAR", "2021"))

BASE = "https://fantasy.nfl.com"


def split_pos_team(pos_team: str):
    """
    'RB - CAR' -> ('RB', 'CAR')
    'K - ' / ' - ' -> handle gracefully
    """
    if not pos_team:
        return "", ""
    parts = [p.strip() for p in pos_team.split("-")]
    if len(parts) == 2:
        return parts[0], parts[1]
    # Fallback (unerwartetes Format)
    return pos_team.strip(), ""


def parse_draft_html(html: str, year: int, league_id: str):
    """
    Parst das Listenlayout der NFL-Draftseite:
    #leagueDraftResultsResults -> div.wrap (je Runde) -> ul > li (je Pick)
    """
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one("#leagueDraftResultsResults")
    results = []

    if not root:
        return results  # nichts da (z. B. Login/Consent)

    for wrap in root.select(".wrap"):
        # Überschrift "Round 1", "Round 2", ...
        h4 = wrap.find("h4")
        round_name = h4.get_text(strip=True) if h4 else ""
        round_num = ""
        m_r = re.search(r"Round\s+(\d+)", round_name, re.I)
        if m_r:
            round_num = m_r.group(1)

        # Einträge
        for li in wrap.select("ul > li"):
            pick_el = li.select_one(".count")
            player_a = li.select_one("a.playerName")
            pos_team_el = li.select_one("em")
            team_name_el = li.select_one(".tw a.teamName")
            manager_li = li.select_one(".tw ul li")

            # Mindestfelder
            if not (pick_el and player_a and pos_team_el and team_name_el):
                continue

            # Picknummer (die NFL zeigt hier den Overall-Pick; falls es doch Rundennummer wäre, reicht es trotzdem)
            try:
                pick_overall = int(pick_el.get_text(strip=True).rstrip("."))
            except Exception:
                # Falls da z. B. '1' ohne Punkt steht
                pick_overall = int(re.sub(r"\D+", "", pick_el.get_text()))

            player_name = player_a.get_text(strip=True)
            pos_team_txt = pos_team_el.get_text(strip=True)  # "RB - CAR"
            dest_team = team_name_el.get_text(strip=True)
            manager = manager_li.get_text(strip=True) if manager_li else ""

            # playerId aus href extrahieren (robuster als Klassen)
            href = player_a.get("href", "")
            m = re.search(r"playerId=(\d+)", href)
            player_id = m.group(1) if m else ""

            pos, nfl_team = split_pos_team(pos_team_txt)

            results.append({
                "year": year,
                "league_id": league_id,
                "round": round_num,
                "pick_overall": pick_overall,
                "player": player_name,
                "player_id": player_id,
                "pos": pos,
                "nfl_team": nfl_team,
                "to_team": dest_team,
                "manager": manager,
            })

    return results


def fetch_year(session: requests.Session, year: int, league_id: str):
    """
    Holt die Draftseite für ein Jahr in der History-Ansicht:
    .../history/<YEAR>/draftresults?draftResultsTab=round&draftResultsType=results
    """
    url = f"{BASE}/league/{league_id}/history/{year}/draftresults"
    params = {
        "draftResultsTab": "round",
        "draftResultsType": "results"
    }
    r = session.get(url, params=params, timeout=30, allow_redirects=True)
    # Debug-Dump zum Nachschauen
    DBG_DIR.mkdir(parents=True, exist_ok=True)
    (DBG_DIR / f"draft_{year}.html").write_text(r.text, encoding="utf-8")
    return r.text, r.url, r.status_code


def write_csv(year: int, rows: list):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"draft_{year}.csv"
    header = [
        "Year", "LeagueId", "Round", "PickOverall",
        "Player", "PlayerId", "Pos", "NFLTeam",
        "DraftedByTeam", "Manager"
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in sorted(rows, key=lambda x: x["pick_overall"]):
            w.writerow([
                r["year"], r["league_id"], r["round"], r["pick_overall"],
                r["player"], r["player_id"], r["pos"], r["nfl_team"],
                r["to_team"], r["manager"]
            ])
    print(f"✓ {year}: {len(rows)} Picks → {out_path}")


def main():
    if not LEAGUE_ID:
        raise SystemExit("LEAGUE_ID fehlt (ENV setzen).")

    s = get_session()

    for year in range(START, END + 1):
        html, final_url, status = fetch_year(s, year, LEAGUE_ID)
        low = html.lower()
        if any(w in low for w in ("sign in", "signin", "login")):
            print(f"[{year}] WARN: Login/Consent erkannt (Status {status}). Prüfe debug/drafts/draft_{year}.html")
            continue

        rows = parse_draft_html(html, year, LEAGUE_ID)
        if not rows:
            print(f"[{year}] Keine Draft-Zeilen erkannt. Prüfe debug/drafts/draft_{year}.html")
        else:
            write_csv(year, rows)


if __name__ == "__main__":
    main()

