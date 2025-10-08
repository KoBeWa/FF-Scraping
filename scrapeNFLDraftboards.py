# -*- coding: utf-8 -*-
"""
Scrape NFL.com Draftboards (History-Seasons) mit BeautifulSoup.
- Nutzt Cookie-Session aus cookieString.get_session()
- Iteriert über Jahre: LEAGUE_START_YEAR..LEAGUE_END_YEAR (inkl.)
- Für jedes Jahr: findet Draft-Seite (versch. mögliche Pfade) und parst die Tabelle
- Output: output/<year>/nfl_draft_<year>.csv mit Feldern:
  Round, Overall, Pick, TeamName, ManagerName, Player, Position, NFLTeam, Bye, DraftUrl

Voraussetzungen:
  - cookieString.py (aus deinem Repo; Cookie in data/nfl_cookie.txt ODER ENV NFL_COOKIE)
  - beautifulsoup4, requests
"""

from __future__ import annotations
import os, sys, csv, re, time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

# Deine Session/Cookies:
from cookieString import get_session

BASE = "https://fantasy.nfl.com"
OUT_DIR = Path("output")
DEBUG_DIR = Path("debug")

LEAGUE_ID = os.getenv("LEAGUE_ID", "").strip()
Y0 = int(os.getenv("LEAGUE_START_YEAR", "2015"))
Y1 = int(os.getenv("LEAGUE_END_YEAR", str(Y0)))

# ----------------------- HTTP & Utils ----------------------- #
def get(url: str, sess: requests.Session, **kw) -> requests.Response:
    r = sess.get(url, timeout=30, allow_redirects=True, **kw)
    r.raise_for_status()
    return r

def save_debug(html: str, year: int, tag: str):
    DEBUG_DIR.mkdir(exist_ok=True, parents=True)
    (DEBUG_DIR / f"draft_{year}_{tag}.html").write_text(html, encoding="utf-8")

def norm_text(x: str | None) -> str:
    return re.sub(r"\s+", " ", (x or "").strip())

def to_int(x, default=None):
    try:
        return int(x)
    except Exception:
        return default

# ----------------------- Draft URL finden ----------------------- #
def history_landing_url(league_id: str, year: int) -> str:
    return f"{BASE}/league/{league_id}/history/{year}"

def draft_candidates(league_id: str, year: int):
    root = history_landing_url(league_id, year)
    # Kandidaten (NFL ändert gelegentlich Pfade/Namen)
    return [
        f"{root}/draftresults",
        f"{root}/draftrecap",
        f"{root}/draft",
        f"{root}/draftboard",
    ]

def find_draft_url(sess: requests.Session, league_id: str, year: int) -> str | None:
    # 1) Versuche History-Landing parsen und Links herausfischen
    try:
        r = get(history_landing_url(league_id, year), sess)
        html = r.text
        save_debug(html, year, "landing")
        soup = BeautifulSoup(html, "html.parser")
        # Links, die nach Draft aussehen
        for a in soup.select("a[href]"):
            href = a["href"]
            if "/draft" in href and str(year) in href:
                if href.startswith("http"):
                    return href
                return BASE + href
    except Exception:
        pass

    # 2) Versuche bekannte Pfade direkt
    for url in draft_candidates(league_id, year):
        try:
            r = get(url, sess)
            if r.status_code == 200 and ("draft" in r.url.lower()):
                # ganz grober Heuristiken-Check
                if any(k in r.text.lower() for k in ["draft", "round", "pick", "overall"]):
                    save_debug(r.text, year, "candidate_hit")
                    return r.url
        except Exception:
            continue

    return None

# ----------------------- Draft-Tabelle parsen ----------------------- #
def is_draft_table(table: BeautifulSoup) -> bool:
    # Prüfe Header
    headers = [norm_text(th.get_text()) for th in table.select("thead th")]
    hlow = [h.lower() for h in headers]
    needed_any = {"player", "pick", "round", "overall", "team", "owner", "manager", "pos", "position"}
    return any(any(k in h for k in needed_any) for h in hlow) or not headers  # manche Seiten ohne <thead>

def extract_manager_team(cell_text: str) -> tuple[str, str]:
    """
    Manche Spalten enthalten 'TeamName (ManagerName)' oder 'Team – Manager'.
    Versuche Team/Manager heuristisch zu trennen.
    """
    t = norm_text(cell_text)
    # "TeamName (ManagerName)"
    m = re.match(r"^(.*?)\s*\((.*?)\)$", t)
    if m:
        return m.group(1), m.group(2)
    # "TeamName – Manager" / "-"
    m = re.match(r"^(.*?)\s*[–-]\s*(.*)$", t)
    if m:
        return m.group(1), m.group(2)
    # sonst alles als TeamName
    return t, ""

def map_headers_to_indexes(headers: list[str]) -> dict[str, int]:
    """
    Mappe verschiedene Header-Varianten auf Ziel-Felder.
    """
    index = {}
    for i, h in enumerate(headers):
        hl = h.lower()
        if "round" in hl:
            index["round"] = i
        elif hl in ("ovr", "overall") or "overall" in hl:
            index["overall"] = i
        elif hl in ("pick", "pick #" , "pick no", "pick number") or "pick" in hl:
            index["pick_in_round"] = i
        elif any(k in hl for k in ["team", "franchise"]):
            index["team"] = i
        elif any(k in hl for k in ["owner", "manager", "gm"]):
            index["manager"] = i
        elif "player" in hl:
            index["player"] = i
        elif hl in ("pos", "position"):
            index["pos"] = i
        elif hl in ("nfl", "nfl team", "team (nfl)", "pro team") or ("team" in hl and "nfl" in hl):
            index["nfl_team"] = i
        elif "bye" in hl:
            index["bye"] = i
    return index

def parse_table(table: BeautifulSoup, draft_url: str, year: int) -> list[dict]:
    rows_out = []
    # Header
    thead = table.find("thead")
    if thead:
        headers = [norm_text(th.get_text()) for th in thead.find_all("th")]
    else:
        # Manche Seiten haben nur <tr><th> im ersten tbody-Row
        first_ths = table.select("tr th")
        headers = [norm_text(th.get_text()) for th in first_ths] if first_ths else []
    index = map_headers_to_indexes(headers)

    # Zeilen
    tr_list = table.select("tbody tr") or table.find_all("tr")
    cur_round = None

    for tr in tr_list:
        tds = tr.find_all(["td", "th"])
        if not tds:
            continue

        # Round kann manchmal als Zeilentrenner kommen
        if len(tds) == 1:
            txt = norm_text(tds[0].get_text())
            # "Round 3" o.ä.
            m = re.search(r"round\s+(\d+)", txt, re.I)
            if m:
                cur_round = to_int(m.group(1), None)
            continue

        # Werte holen (robust gegen fehlende Spalten)
        def _get(idx_key, default=""):
            i = index.get(idx_key)
            if i is not None and i < len(tds):
                return norm_text(tds[i].get_text())
            return default

        round_txt = _get("round", "")
        pick_overall = _get("overall", "")
        pick_in_round = _get("pick_in_round", "")
        team_txt = _get("team", "")
        manager_txt = _get("manager", "")
        player_txt = _get("player", "")
        pos_txt = _get("pos", "")
        nflteam_txt = _get("nfl_team", "")
        bye_txt = _get("bye", "")

        # Falls Round-Header fehlt, aber wir haben cur_round (Zeilentrenner vorab)
        if not round_txt and cur_round:
            round_txt = str(cur_round)

        # Team/Manager eventuell in einer Spalte kombiniert
        if team_txt and not manager_txt:
            team_txt, manager_txt = extract_manager_team(team_txt)

        # Manche Tabellen haben „Team – Manager“ andersherum – Versuch:
        if (not team_txt) and manager_txt and " - " in manager_txt:
            parts = [p.strip() for p in manager_txt.split(" - ", 1)]
            if len(parts) == 2:
                team_txt, manager_txt = parts[0], parts[1]

        # Player, Pos, NFL Team evtl. als Link/Nested
        # Bereits norm_text() angewendet

        # Skip, wenn Zeile offensichtlich kein Pick ist
        if not player_txt and not pick_in_round and not pick_overall:
            continue

        rows_out.append({
            "Round": round_txt,
            "Overall": pick_overall,
            "Pick": pick_in_round,
            "TeamName": team_txt,
            "ManagerName": manager_txt,
            "Player": player_txt,
            "Position": pos_txt,
            "NFLTeam": nflteam_txt,
            "Bye": bye_txt,
            "DraftUrl": draft_url,
            "Season": year,
        })

    return rows_out

def parse_draft_page(html: str, draft_url: str, year: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    # 1) Primär: Tabellen
    tables = soup.find_all("table")
    candidates = [t for t in tables if is_draft_table(t)]
    rows = []
    for t in candidates:
        rows.extend(parse_table(t, draft_url, year))

    # 2) Fallbacks (falls Seite ein Kartenlayout hat, hier nur einfacher Sketch):
    if not rows:
        cards = soup.select(".draftPick, .pick, .draft-pick, li.pick")  # heuristisch
        overall = 0
        for c in cards:
            overall += 1
            txt = norm_text(c.get_text(" "))
            # sehr grob: Player (Pos - Team) extrahieren, Round/Pick erraten
            m = re.search(r"^(.*?)\s+\(?([A-Z]{1,3})\)?\s*[-–]\s*([A-Z]{2,3})", txt)
            player, pos, nflteam = ("", "", "")
            if m:
                player, pos, nflteam = m.groups()
            rows.append({
                "Round": "",
                "Overall": str(overall),
                "Pick": "",
                "TeamName": "",
                "ManagerName": "",
                "Player": player,
                "Position": pos,
                "NFLTeam": nflteam,
                "Bye": "",
                "DraftUrl": draft_url,
                "Season": year,
            })

    return rows

# ----------------------- MAIN ----------------------- #
def main():
    if not LEAGUE_ID:
        raise SystemExit("Bitte LEAGUE_ID als ENV setzen.")
    sess = get_session()
    # kleiner Referer hilft manchmal
    sess.headers.setdefault("Referer", f"{BASE}/myleagues")

    any_rows = 0

    for year in range(Y0, Y1 + 1):
        print(f"\n=== Saison {year} ===")
        try:
            draft_url = find_draft_url(sess, LEAGUE_ID, year)
            if not draft_url:
                print(f"⚠️  Keine Draft-Seite gefunden ({year}). Landing HTML unter debug/ prüfen.")
                continue

            print("→ Draft-Seite:", draft_url)
            r = get(draft_url, sess)
            html = r.text
            save_debug(html, year, "draftpage")

            rows = parse_draft_page(html, draft_url, year)
            if not rows:
                print("⚠️  Keine Draft-Zeilen erkannt. debug/draft_* ansehen.")
                continue

            # Output-Ordner
            outdir = OUT_DIR / str(year)
            outdir.mkdir(parents=True, exist_ok=True)
            out_csv = outdir / f"nfl_draft_{year}.csv"

            with out_csv.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=["Round","Overall","Pick","TeamName","ManagerName","Player","Position","NFLTeam","Bye","DraftUrl","Season"]
                )
                w.writeheader()
                for row in rows:
                    w.writerow(row)

            any_rows += len(rows)
            print(f"✓ {len(rows)} Picks geschrieben → {out_csv}")

        except requests.HTTPError as e:
            print(f"HTTPError {year}: {e}")
        except Exception as e:
            print(f"Fehler {year}: {e}")

    if any_rows == 0:
        print("\nHinweis: Wenn überall Login/Consent kommt, ist der Cookie ungültig/abgelaufen.")
        print("➡  data/nfl_cookie.txt erneuern oder ENV NFL_COOKIE setzen (Request-Header „Cookie:“).")

if __name__ == "__main__":
    main()
