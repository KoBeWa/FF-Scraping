# scrapeNFLDraftboards.py
import os, csv, pathlib, urllib.parse, time
import requests
from bs4 import BeautifulSoup
from cookieString import get_session  # nutzt dein Cookie/Session-Setup

def draft_url(league_id: str, year: str) -> str:
    base = f"https://fantasy.nfl.com/league/{league_id}/history/{year}/draftresults"
    qs = {
        "draftResultsDetail": "0",
        "draftResultsTab": "round",
        "draftResultsType": "results",
    }
    return base + "?" + urllib.parse.urlencode(qs)

def parse_draft(html: str):
    """
    Minimales Beispiel:
    - Sucht die Draft-Tabelle(n) und liefert eine Liste Zeilen: 
      [round, overall_pick, pick_in_round, team_name, manager, player_name, pos, nfl_team]
    Passe die Selektoren an das tatsächliche Markup deiner Liga an.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows_out = []

    # Häufig gibt es eine Tabelle mit Zeilen pro Pick.
    # Suche konservativ:
    for tbl in soup.select("table"):  # ggf. enger: table.tableType.draftresults
        headers = [th.get_text(strip=True).lower() for th in tbl.select("thead th")]
        # Minimalprüfung, ob das wie eine Drafttabelle aussieht
        if not any("round" in h for h in headers) and not any("pick" in h for h in headers):
            continue

        for tr in tbl.select("tbody tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.select("td")]
            if len(tds) < 3:
                continue
            # Versuche, generisch Felder zu erkennen:
            # häufige Reihenfolgen: Round | Pick (Overall) | Pick (Round) | Team | Player | (Pos/Team)
            txt = " | ".join(tds).lower()
            if "draft" in txt or "round" in txt or "pick" in txt:
                # sehr generisch; passe für deine Liga an:
                round_        = tds[0] if len(tds) > 0 else ""
                overall_pick  = tds[1] if len(tds) > 1 else ""
                pick_in_round = tds[2] if len(tds) > 2 else ""
                team_name     = tds[3] if len(tds) > 3 else ""
                player_blob   = tds[4] if len(tds) > 4 else ""
                # Aus player_blob grob Name/Pos/Team ziehen:
                # z.B. "Patrick Mahomes (QB - KC)"
                player_name, pos, nfl_team = player_blob, "", ""
                if "(" in player_blob and ")" in player_blob:
                    core = player_blob[player_blob.find("(")+1:player_blob.rfind(")")]
                    # "QB - KC" → split
                    if " - " in core:
                        pos, nfl_team = [x.strip() for x in core.split(" - ", 1)]
                    player_name = player_blob[:player_blob.find("(")].strip()

                rows_out.append([
                    round_, overall_pick, pick_in_round, team_name, player_name, pos, nfl_team
                ])

    return rows_out

def main():
    lid  = os.getenv("LEAGUE_ID", "").strip()
    y0   = int(os.getenv("LEAGUE_START_YEAR", "2015"))
    y1   = int(os.getenv("LEAGUE_END_YEAR",   "2021"))
    assert lid, "LEAGUE_ID fehlt"

    outdir = pathlib.Path("output/drafts")
    dbgdir = pathlib.Path("debug/drafts")
    outdir.mkdir(parents=True, exist_ok=True)
    dbgdir.mkdir(parents=True, exist_ok=True)

    s = get_session()

    for year in range(y0, y1 + 1):
        url = draft_url(lid, str(year))
        r = s.get(url, timeout=30, allow_redirects=True)
        dbgpath = dbgdir / f"draft_{year}.html"
        dbgpath.write_text(r.text, encoding="utf-8")

        if r.status_code != 200:
            print(f"[{year}] HTTP {r.status_code} → übersprungen")
            continue

        rows = parse_draft(r.text)
        if not rows:
            print(f"[{year}] Keine Draft-Zeilen erkannt. Prüfe {dbgpath}")
            continue

        out = outdir / f"draft_{year}.csv"
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Round","OverallPick","PickInRound","TeamName","Player","Pos","NFLTeam"])
            w.writerows(rows)
        print(f"✓ {out} ({len(rows)} Zeilen)")

        time.sleep(1.0)  # höfliche Pause

if __name__ == "__main__":
    main()

