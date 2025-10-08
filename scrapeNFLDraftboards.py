# scrapeNFLDraftboards.py
import os
import csv
import re
import urllib.parse
from pathlib import Path

from bs4 import BeautifulSoup
from cookieString import get_session

OUT = Path("output/nfl_drafts")
DBG = Path("debug/drafts")
OUT.mkdir(parents=True, exist_ok=True)
DBG.mkdir(parents=True, exist_ok=True)

LEAGUE_ID = os.getenv("LEAGUE_ID", "").strip()
START = int(os.getenv("LEAGUE_START_YEAR", "2015"))
END   = int(os.getenv("LEAGUE_END_YEAR", "2021"))

HEADERS = [
    "Year","Round","OverallPick","TeamName","ManagerName",
    "Player","Position","NFLTeam","Notes"
]

LOGIN_MARKERS = ("sign in", "signin", "login", "forgot password", "create account")

def looks_like_login(html: str, url: str) -> bool:
    low = html.lower()
    if any(k in low for k in LOGIN_MARKERS):
        return True
    if "/login" in url or "/signin" in url:
        return True
    return False

def clean_txt(x):
    return re.sub(r"\s+", " ", (x or "")).strip()

def parse_table_based(soup: BeautifulSoup):
    """
    Versucht, tabellarische Draft-Daten zu lesen (mehrere mögliche Strukturen).
    """
    results = []

    # Kandidaten-Tabellen: id/class enthält 'draft'
    tables = []
    for t in soup.find_all("table"):
        id_ = (t.get("id") or "").lower()
        cls = " ".join(t.get("class") or []).lower()
        if any(k in id_ for k in ("draft", "results")) or any(k in cls for k in ("draft", "results")):
            tables.append(t)

    # Fallback: keine offensichtliche Draft-Tabelle → nimm alle Tabellen
    if not tables:
        tables = soup.find_all("table")

    for table in tables:
        # Header prüfen – ob irgendwie nach Draft aussieht
        hdr_txt = " ".join(th.get_text(" ", strip=True) for th in table.find_all("th"))
        if not any(k in hdr_txt.lower() for k in ("round", "pick", "overall", "player")):
            # könnte dennoch eine subtable sein – wir versuchen trotzdem
            pass

        for tr in table.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if len(tds) < 3:
                continue

            row_txts = [clean_txt(td.get_text(" ", strip=True)) for td in tds]
            row_join = " ".join(row_txts).lower()
            # heuristisch: muss irgendwo Pick/Player vorkommen
            if not any(k in row_join for k in ("pick", "player", "round")):
                continue

            # Versuche Round / Overall aus Zellen oder aus einer "Round X" Überschrift
            round_no = None
            overall = None
            team_name = ""
            manager = ""
            player = ""
            pos = ""
            nfl_team = ""
            notes = ""

            # Häufige Muster:
            # [Round, Overall, Pick(by team/manager), Player (POS - NFL), ...]
            # Oder: Overall, Team/Manager, Player, POS, NFL
            txts = [t.strip() for t in row_txts]

            # Round
            for t in txts:
                m = re.search(r"\bround\s*(\d+)", t, flags=re.I)
                if m:
                    round_no = m.group(1)
                    break
            # Overall
            for t in txts:
                m = re.search(r"\boverall\s*pick\s*(\d+)|\boverall\s*(\d+)|^\s*(\d+)\s*$", t, flags=re.I)
                if m:
                    overall = next(g for g in m.groups() if g)
                    break

            # Player + (POS - NFL)
            for t in txts:
                # z.B. "Christian McCaffrey RB - CAR"
                m = re.search(r"(.+?)\s+([A-Z]{1,3})\s*-\s*([A-Z]{2,3})$", t)
                if m:
                    player, pos, nfl_team = m.group(1), m.group(2), m.group(3)
                    break

            # Team/Manager (z. B. "Drafted by Los Cheezos Ritzos (LosSausages)")
            for t in txts:
                if "drafted by" in t.lower():
                    take = t.split(":", 1)[-1].strip() if ":" in t else t
                    # Hole evtl. "Team (Manager)"
                    m = re.search(r"(.+?)\s*\((.+?)\)", take)
                    if m:
                        team_name, manager = m.group(1).strip(), m.group(2).strip()
                    else:
                        team_name = take
                    break
            if not team_name:
                # Look for a cell that contains parentheses pair likely team(manager)
                for t in txts:
                    m = re.search(r"(.+?)\s*\((.+?)\)", t)
                    if m and all(len(x) > 1 for x in m.groups()):
                        team_name, manager = m.group(1).strip(), m.group(2).strip()
                        break

            # Fallbacks, wenn nichts extrahiert wurde – versuche die häufigste Spaltenordnung:
            # 0: Overall, 1: Team/Manager, 2: Player, 3: POS, 4: NFL
            if overall is None:
                m = re.match(r"^\d+$", txts[0]) if txts else None
                if m:
                    overall = txts[0]
            if not player and len(txts) >= 3:
                player = txts[2]
            if not pos and len(txts) >= 4:
                pos = txts[3]
            if not nfl_team and len(txts) >= 5:
                nfl_team = txts[4]

            # Minimalanforderung: mindestens Player ODER Overall muss da sein
            if not player and not overall:
                continue

            results.append({
                "Round": round_no or "",
                "OverallPick": overall or "",
                "TeamName": team_name,
                "ManagerName": manager,
                "Player": player,
                "Position": pos,
                "NFLTeam": nfl_team,
                "Notes": "",
            })

    return results

def parse_list_based(soup: BeautifulSoup):
    """
    Manche Jahre sind als <ul>/<li> gelistet.
    """
    results = []
    # Kandidaten-Container
    containers = []
    for tag in soup.find_all(["ul", "ol", "div", "section"]):
        id_ = (tag.get("id") or "").lower()
        cls = " ".join(tag.get("class") or []).lower()
        txt = (tag.get_text(" ", strip=True) or "").lower()
        if any(k in id_ for k in ("draft", "results")) or any(k in cls for k in ("draft", "results")) or "draft" in txt[:200]:
            containers.append(tag)

    if not containers:
        containers = [soup]

    for cont in containers:
        for li in cont.find_all(["li", "div"], recursive=True):
            txt = clean_txt(li.get_text(" ", strip=True))
            low = txt.lower()
            if not any(k in low for k in ("pick", "player")):
                continue

            round_no = None
            overall = None
            team_name = ""
            manager = ""
            player = ""
            pos = ""
            nfl_team = ""
            notes = ""

            m = re.search(r"\bround\s*(\d+)", txt, flags=re.I)
            if m:
                round_no = m.group(1)
            m = re.search(r"\boverall\s*pick\s*(\d+)|\boverall\s*(\d+)|\bpick\s*(\d+)", txt, flags=re.I)
            if m:
                overall = next(g for g in m.groups() if g)

            m = re.search(r"(.+?)\s+([A-Z]{1,3})\s*-\s*([A-Z]{2,3})", txt)
            if m:
                player, pos, nfl_team = m.group(1), m.group(2), m.group(3)

            m = re.search(r"drafted by\s*([^()]+)\s*(\(([^)]+)\))?", txt, flags=re.I)
            if m:
                team_name = (m.group(1) or "").strip()
                manager = (m.group(3) or "").strip()

            if not player and not overall:
                continue

            results.append({
                "Round": round_no or "",
                "OverallPick": overall or "",
                "TeamName": team_name,
                "ManagerName": manager,
                "Player": player,
                "Position": pos,
                "NFLTeam": nfl_team,
                "Notes": "",
            })

    return results

def scrape_year(year: int):
    from bs4 import BeautifulSoup  # local import to ensure bs4 installed
    import requests

    s = get_session()
    base = f"https://fantasy.nfl.com/league/{LEAGUE_ID}/history/{year}/draftresults"
    qs = {"draftResultsDetail":"0","draftResultsTab":"round","draftResultsType":"results"}
    url = base + "?" + urllib.parse.urlencode(qs)

    r = s.get(url, timeout=40, allow_redirects=True)
    DBG.joinpath(f"draft_{year}.html").write_text(r.text, encoding="utf-8")

    if looks_like_login(r.text, r.url):
        print(f"[{year}] Sieht nach Login/Fehler aus – prüfe debug/drafts/draft_{year}.html")
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    rows = parse_table_based(soup)
    if not rows:
        rows = parse_list_based(soup)

    return rows

def main():
    if not LEAGUE_ID:
        raise SystemExit("LEAGUE_ID fehlt (ENV).")

    any_ok = False
    for year in range(START, END + 1):
        rows = scrape_year(year)
        if not rows:
            print(f"[{year}] Keine Draft-Zeilen erkannt. Prüfe debug/drafts/draft_{year}.html")
            continue

        out = OUT / f"{year}_draft.csv"
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=HEADERS)
            w.writeheader()
            for r in rows:
                r2 = {
                    "Year": year,
                    **r
                }
                w.writerow(r2)
        any_ok = True
        print(f"[{year}] ✓ {len(rows)} Picks → {out}")

    if not any_ok:
        raise SystemExit("Keine Drafts geparst. Siehe debug/drafts/*.html für das tatsächliche Markup.")

if __name__ == "__main__":
    main()
