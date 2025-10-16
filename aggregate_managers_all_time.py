# aggregate_managers_all_time.py
import csv, json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "output"
ALL_TIME_DIR = OUT_DIR / "all_time"
ALIASES_PATH = ROOT / "aliases.json"  # optional

def autodelim(p: Path) -> str:
    sample = p.read_text("utf-8", errors="ignore")[:4096]
    return "\t" if sample.count("\t") >= sample.count(",") else ","

def read_rows(p: Path):
    delim = autodelim(p)
    with p.open("r", encoding="utf-8", newline="") as f:
        rdr = csv.reader(f, delimiter=delim)
        header = next(rdr, [])
        header = [h.strip() for h in header]
        for row in rdr:
            yield {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}

def to_float(x):
    s = str(x or "").strip().replace(" ", "")
    if s.count(",") > 0 and s.count(".") > 0:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")  # deutsch
        else:
            s = s.replace(",", "")                    # englisch mit tausender-Komma
    else:
        s = s.replace(",", ".")
    try: return float(s)
    except: return 0.0

def load_aliases():
    if not ALIASES_PATH.exists():
        return {}
    with ALIASES_PATH.open("r", encoding="utf-8") as f:
        j = json.load(f)
    return j.get("manager", {})

def alias_name(name, manager_aliases):
    n = " ".join(str(name or "").split())
    return manager_aliases.get(n, n)

# ---------- Regular aus standings_regular_1_14.tsv ----------
def parse_regular(season_dir: Path):
    p = season_dir / "standings_regular_1_14.tsv"
    res = {}
    if not p.exists():
        return res
    for r in read_rows(p):
        m = r.get("ManagerName") or r.get("Owner") or ""
        if not m: continue
        # Record: "W-L-T"
        rec = (r.get("Record") or "").strip()
        try:
            w, l, t = [int(x) for x in rec.split("-")]
        except:
            w = l = t = 0
        pf = to_float(r.get("PointsFor"))
        pa = to_float(r.get("PointsAgainst"))
        moves  = to_float(r.get("Moves"))
        trades = to_float(r.get("Trades"))
        dp_raw = r.get("DraftPosition")
        dp = to_float(dp_raw) if dp_raw not in (None, "",) else None
        res[m] = {
            "W": w, "L": l, "T": t,
            "PF": pf, "PA": pa,
            "Moves": moves, "Trades": trades,
            "DraftPosition": dp
        }
    return res

# ---------- Playoffs aus standings_playoffs.tsv ----------
def parse_playoffs(season_dir: Path):
    """
    Erwartet Spalten: TeamName, PlayoffRank, ManagerName, Seed, Week15Pts, Week16Pts
    Gibt zurück:
      seeds (dict manager -> seed),
      pts15/pts16 (dict manager -> float),
      prank (dict manager -> int PlayoffRank)
    """
    p = season_dir / "standings_playoffs.tsv"
    seeds, pts15, pts16, prank = {}, {}, {}, {}
    if not p.exists():
        return seeds, pts15, pts16, prank
    for r in read_rows(p):
        m = r.get("ManagerName") or r.get("Owner") or ""
        if not m: continue
        seed = int(to_float(r.get("Seed")))
        s15  = to_float(r.get("Week15Pts"))
        s16  = to_float(r.get("Week16Pts"))
        pr   = int(to_float(r.get("PlayoffRank")))
        seeds[m] = seed
        pts15[m] = s15
        pts16[m] = s16
        prank[m] = pr
    return seeds, pts15, pts16, prank

def playoff_wlt_and_pfpa_from_bracket(seeds, pts15, pts16):
    """
    Rekonstruiert die Spiele:
      W15: 1v4, 2v3, 5v8, 6v7
      W16: Sieger(1v4) vs Sieger(2v3); Verlierer vs Verlierer
           Sieger(5v8) vs Sieger(6v7); Verlierer vs Verlierer
    Tiebreak bei exakt gleichen Punkten: besserer Seed gewinnt.
    Rückgabe: dict manager -> {"W":..,"L":..,"T":0,"PF_add":..,"PA_add":..}
    """
    # Nur Teams mit Seed 1..8 beachten
    top8 = {m: s for m, s in seeds.items() if 1 <= s <= 8}
    # reverse lookup: seed -> manager
    seed_to_mgr = {s: m for m, s in top8.items()}

    def pair(seed_a, seed_b):  # returns (mgrA, mgrB)
        return seed_to_mgr.get(seed_a), seed_to_mgr.get(seed_b)

    def winner(a, b, week):
        pa = pts15[a] if week == 15 else pts16[a]
        pb = pts15[b] if week == 15 else pts16[b]
        if pa > pb: return a, b
        if pb > pa: return b, a
        # tiebreak: besserer Seed gewinnt
        return (a if seeds[a] < seeds[b] else b), (b if seeds[a] < seeds[b] else a)

    out = {m: {"W":0,"L":0,"T":0,"PF_add":0.0,"PA_add":0.0} for m in top8.keys()}

    # Punkte addieren (PF) – PA brauchen wir pro Matchup
    for m in top8.keys():
        out[m]["PF_add"] += pts15.get(m, 0.0)
        out[m]["PF_add"] += pts16.get(m, 0.0)

    # Week 15 Paarungen
    qf = [
        pair(1,4), pair(2,3), pair(5,8), pair(6,7)
    ]
    # Zähle W/L & PA für Week 15
    for a, b in qf:
        if not a or not b: continue
        wa, la = winner(a,b,15)
        # PA
        out[a]["PA_add"] += pts15.get(b, 0.0)
        out[b]["PA_add"] += pts15.get(a, 0.0)
        # W/L
        out[wa]["W"] += 1
        out[la]["L"] += 1

    # Bestimme Finals & Consolations für Week 16
    # Top: Seeds 1–4
    a14, b23 = pair(1,4), pair(2,3)
    if all(a14) and all(b23):
        w14, l14 = winner(a14[0], a14[1], 15)
        w23, l23 = winner(b23[0], b23[1], 15)
        top_final = (w14, w23)
        top_third = (l14, l23)
    else:
        top_final = top_third = (None, None)

    # Bottom: Seeds 5–8
    a58, b67 = pair(5,8), pair(6,7)
    if all(a58) and all(b67):
        w58, l58 = winner(a58[0], a58[1], 15)
        w67, l67 = winner(b67[0], b67[1], 15)
        bot_final = (w58, w67)
        bot_third = (l58, l67)
    else:
        bot_final = bot_third = (None, None)

    # Week 16: W/L & PA
    for a,b in [top_final, top_third, bot_final, bot_third]:
        if not a or not b: continue
        wa, la = winner(a,b,16)
        out[a]["PA_add"] += pts16.get(b, 0.0)
        out[b]["PA_add"] += pts16.get(a, 0.0)
        out[wa]["W"] += 1
        out[la]["L"] += 1

    return out

def main():
    manager_aliases = load_aliases()

    agg = defaultdict(lambda: {
        "PF":0.0,"PA":0.0,"Moves":0.0,"Trades":0.0,
        "W":0,"L":0,"T":0,"Championships":0,"Playoffs":0,"Sackos":0,
        "DP_sum":0.0,"DP_n":0,"Seasons":0,"Finals":0,"ToiletBowls":0, 
    })

    season_dirs = sorted([p for p in OUT_DIR.iterdir() if p.is_dir() and p.name.isdigit()], key=lambda p: int(p.name))

    for sdir in season_dirs:
        # Regular
        reg = parse_regular(sdir)  # m -> dict
        # Playoffs
        seeds, pts15, pts16, prank = parse_playoffs(sdir)

        # Bracket-W/L/PF/PA aus Playoffs rekonstruieren
        playoff_calc = playoff_wlt_and_pfpa_from_bracket(seeds, pts15, pts16) if seeds else {}

        # Saisonweite Liste Managernamen (nach Alias) für Seasons-Zähler
        managers_this_season = set()

        # 1) Regular in Aggregat
        for m_raw, sv in reg.items():
            m = alias_name(m_raw, manager_aliases)
            a = agg[m]
            a["PF"]     += sv["PF"]
            a["PA"]     += sv["PA"]
            a["W"]      += sv["W"]
            a["L"]      += sv["L"]
            a["T"]      += sv["T"]
            a["Moves"]  += sv["Moves"]
            a["Trades"] += sv["Trades"]
            if sv["DraftPosition"] is not None:
                a["DP_sum"] += float(sv["DraftPosition"])
                a["DP_n"]   += 1
            managers_this_season.add(m)

        # 2) Playoffs hinzufügen
        for m_raw, seed in seeds.items():
            m = alias_name(m_raw, manager_aliases)
            add = playoff_calc.get(m_raw)  # Achtung: playoff_calc key = raw name, da Seed/Punkte aus Datei
            if add:
                a = agg[m]
                a["PF"] += add["PF_add"]
                a["PA"] += add["PA_add"]
                a["W"]  += add["W"]
                a["L"]  += add["L"]
                # Ties in Playoffs existieren faktisch nicht (Seed-Tiebreak) → T bleibt 0

        # 3) Championships / Sackos / Playoffs (nur Seeds 1–4 zählen als Teilnahme)
        for m_raw, pr in prank.items():
            m = alias_name(m_raw, manager_aliases)
            if pr == 1:
                agg[m]["Championships"] += 1
            # „Sacko“ hier optional weitergeführt: nimm Rank 8 als „Sacko“
            if pr == 8:
                agg[m]["Sackos"] += 1
            if pr in (1, 2):
                agg[m]["Finals"] += 1
            if pr in (7, 8):
                agg[m]["ToiletBowls"] += 1

        for m_raw, seed in seeds.items():
            if 1 <= seed <= 4:  # nur Top-4 als Playoff-Teilnahme
                m = alias_name(m_raw, manager_aliases)
                agg[m]["Playoffs"] += 1

        # 4) Seasons-Zähler erhöhen
        for m in managers_this_season:
            agg[m]["Seasons"] += 1

    # Ausgabe
    ALL_TIME_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ALL_TIME_DIR / "aggregated_standings.tsv"
    header = [
        "ManagerName","PointsFor","PointsAgainst","Moves","Trades",
        "Wins","Losses","Ties","Championships","Playoffs","Finals","ToiletBowls","Sackos",
        "DraftPosition","Seasons"
    ]

    rows = []
    for m, s in agg.items():
        dp_avg = (s["DP_sum"] / s["DP_n"]) if s["DP_n"] else ""
        rows.append([
            m,
            f"{s['PF']:.10g}",
            f"{s['PA']:.10g}",
            f"{s['Moves']:.1f}",
            f"{s['Trades']:.1f}",
            s["W"], s["L"], s["T"],
            s["Championships"], s["Playoffs"], s["Finals"], s["ToiletBowls"], s["Sackos"],
            f"{dp_avg:.1f}" if dp_avg != "" else "",
            s["Seasons"]
        ])

    # Sortierung: frei wählbar – hier z. B. nach Wins ↓, PF ↓
    rows.sort(key=lambda r: (r[5], float(r[1])), reverse=True)

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(header)
        w.writerows(rows)

    print(f"✓ {out_path}")

if __name__ == "__main__":
    main()
