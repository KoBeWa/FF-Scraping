import csv
from bs4 import BeautifulSoup as bs
import requests
from cookieString import cookies
from utils import setup_output_folders
from constants import leagueID, leagueStartYear, leagueEndYear, standings_directory


# Iterate through each season
# Parse standings, owners, and draft results
# Write to a csv file
for i in range(leagueStartYear, leagueEndYear):
    season = str(i)
    setup_output_folders(leagueID, season)

    # Parse Regular Season Standings
    # https://fantasy.nfl.com/league/1609009/history/2023/standings?historyStandingsType=regular
    page = requests.get('https://fantasy.nfl.com/league/' + leagueID + '/history/' + season + '/standings?historyStandingsType=regular', cookies=cookies)
    soup = bs(page.text, 'html.parser')
    csv_rows = []

    # Parse the regular season standings table
    # Adds cols: 'TeamName', 'RegularSeasonRank', 'Record', 'PointsFor', 'PointsAgainst'
    season_table_rows = soup.find_all('tr', class_=lambda x: x and 'team' in x)
    for row in season_table_rows:
        season_rank = row.find('span', class_='teamRank').text.strip()
        team_name = row.find('a', class_='teamName').text.strip()
        team_record = row.find('td', class_='teamRecord').text.strip()
        pts_for = row.find_all('td', class_='teamPts')[0].text.strip()
        pts_against = row.find_all('td', class_='teamPts')[1].text.strip()
        csv_rows.append([team_name, season_rank, team_record, pts_for, pts_against])

    # Parse Playoffs Season Standings
    # https://fantasy.nfl.com/league/1609009/history/2023/standings?historyStandingsType=final
    page = requests.get('https://fantasy.nfl.com/league/' + leagueID + '/history/' + season + '/standings?historyStandingsType=final', cookies=cookies)
    soup = bs(page.text, 'html.parser')

    # Parse the playoffs standings table
    # Adds col: 'PlayoffRank'
    playoff_table_rows = soup.find_all('li', class_=lambda x: x and 'place' in x)
    for row in playoff_table_rows:
        # Find the div with class 'place' to extract the place number
        place_div = row.find('div', class_='place')
        if place_div:
            # Extract the place number from the text
            place_number = place_div.text.split()[0][:-2]
            # Find the anchor tag within the div with class 'value' to extract the team name
            team_name_anchor = row.find('div', class_='value').find('a', class_='teamName')
            if team_name_anchor:
                team_name = team_name_anchor.text.strip()
                for csv_row in csv_rows:
                    if csv_row[0] == team_name:
                        csv_row.append(place_number)

    # Parse Owners
    # https://fantasy.nfl.com/league/1609009/history/2023/owners
    page = requests.get('https://fantasy.nfl.com/league/' + leagueID + '/history/' + season + '/owners', cookies=cookies)
    soup = bs(page.text, 'html.parser')

    # Parse the owners table
    # Adds cols: 'ManagerName', 'Moves', 'Trades'
    season_table_rows = soup.find_all('tr', class_=lambda x: x and 'team' in x)
    for row in season_table_rows:
        team_name = row.find('a', class_='teamName').text.strip()
        manager = row.find('span', class_='userName').text.strip()
        moves = row.find('td', class_='teamTransactionCount').text.strip()
        trades = row.find('td', class_='teamTradeCount').text.strip()
        for csv_row in csv_rows:
            if csv_row[0] == team_name:
                csv_row.append(manager)
                csv_row.append(moves)
                csv_row.append(trades)

    # Parse Draft Results
    # https://fantasy.nfl.com/league/1609009/history/2023/draftresults
    page = requests.get('https://fantasy.nfl.com/league/' + leagueID + '/history/' + season + '/draftresults', cookies=cookies)
    soup = bs(page.text, 'html.parser')

    # Parse the Draft results table (robust) – Adds col: 'DraftPosition'
    # https://fantasy.nfl.com/league/<id>/history/<season>/draftresults
    try:
        url_draft = f"https://fantasy.nfl.com/league/{leagueID}/history/{season}/draftresults"
        soup = get_soup(url_draft) if 'get_soup' in globals() else bs(requests.get(url_draft, headers=HEADERS, cookies=cookies, timeout=30).text, 'html.parser')
    
        # 1) Versuche "Round 1" Header tolerant zu finden
        draft_h4 = None
        for h in soup.find_all('h4'):
            txt = (h.get_text(strip=True) or '').lower()
            if txt.startswith('round 1') or txt == 'round 1':
                draft_h4 = h
                break
    
        round_1_ul = None
        if draft_h4:
            # Nächstes UL nach dem Header
            round_1_ul = draft_h4.find_next(lambda tag: tag.name == 'ul' and tag.find('span', class_='count'))
        else:
            # 2) Fallback: irgendein UL, das Draft-Picks (span.count) enthält
            for ul in soup.find_all('ul'):
                if ul.find('span', class_='count') and ul.find('a', class_='teamName'):
                    round_1_ul = ul
                    break
    
        if round_1_ul:
            for li in round_1_ul.find_all('li'):
                draft_position = li.find('span', class_='count')
                team_anchor = li.find('a', class_='teamName')
                if draft_position and team_anchor:
                    pos = draft_position.get_text(strip=True).rstrip(".#")
                    team_name = team_anchor.get_text(strip=True)
                    for csv_row in csv_rows:
                        if csv_row[0] == team_name:
                            while len(csv_row) < 9:  # bis Trades auffüllen
                                csv_row.append("")
                            # DraftPosition anhängen/setzen
                            if len(csv_row) == 9:
                                csv_row.append(pos)
                            else:
                                csv_row[9] = pos
        else:
            print(f"[{season}] Draft Round 1 nicht gefunden – Seite sieht anders aus / keine Daten. Skipping.")
    
    except Exception as e:
        print(f"[{season}] Draft-Parsing Fehler: {e}")
        # Dump HTML zur Analyse in Actions-Artifact
        try:
            os.makedirs("debug_html", exist_ok=True)
            with open(f"debug_html/draft_{season}.html", "w", encoding="utf-8") as fh:
                fh.write(str(soup))
            print(f"[{season}] Draft HTML gedumpt nach debug_html/draft_{season}.html")
        except Exception as _:
            pass

                
    # Write all to a csv file
    with open(standings_directory + season + '.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        header= ['TeamName', 'RegularSeasonRank', 'Record', 'PointsFor', 'PointsAgainst', 'PlayoffRank', 'ManagerName', 'Moves', "Trades", "DraftPosition"]
        writer.writerow(header) 
        for row in csv_rows:
            writer.writerow(row)

    print(season + " parsed.")

