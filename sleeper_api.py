# sleeper_api.py
import requests

BASE = "https://api.sleeper.app/v1"

def get_league(league_id):           return requests.get(f"{BASE}/league/{league_id}").json()
def get_league_users(league_id):     return requests.get(f"{BASE}/league/{league_id}/users").json()
def get_league_rosters(league_id):   return requests.get(f"{BASE}/league/{league_id}/rosters").json()
def get_matchups(league_id, week):   return requests.get(f"{BASE}/league/{league_id}/matchups/{week}").json()
def get_winners_bracket(league_id):  return requests.get(f"{BASE}/league/{league_id}/winners_bracket").json()
def get_losers_bracket(league_id):   return requests.get(f"{BASE}/league/{league_id}/losers_bracket").json()
def get_user_leagues(user_id, season): return requests.get(f"{BASE}/user/{user_id}/leagues/nfl/{season}").json()
