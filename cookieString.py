# cookieString.py
import os, time, pathlib, requests
from urllib.parse import urlencode

def _read_cookie_string() -> str:
    v = os.getenv("NFL_COOKIE", "").strip()
    if v:
        return v
    p = pathlib.Path("data/nfl_cookie.txt")
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""

def _parse_cookie_string(s: str) -> dict:
    jar = {}
    if not s:
        return jar
    # Falls versehentlich mit "Cookie:" kopiert wurde
    low = s.lower().lstrip()
    if low.startswith("cookie:"):
        s = s.split(":", 1)[1].strip()
    # In einzelne Paare zerlegen
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    return jar

def _maybe_set_consent_cookies(sess: requests.Session):
    # Minimal „OK“-Consent, damit OneTrust nicht blockt (wird oft akzeptiert)
    now = time.strftime("Wed Oct %d %Y %H:%M:%S GMT+0200 (Mitteleuropäische Sommerzeit)", time.localtime())
    sess.cookies.set("OptanonAlertBoxClosed", time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()))
    # Sehr permissiver Consent (wie ein echter Opt-In). Wenn dein echter Cookie diese Keys schon hat, überschreibt das requests NICHT.
    consent = (
        "isGpcEnabled=0&version=202411.1.0&browserGpcFlag=0&isIABGlobal=false&"
        f"datestamp={now}&groups=C0001:1,C0002:1,C0003:1,C0004:1,V2STACK42:1&"
        "isAnonUser=0&landingPath=NotLandingPage&AwaitingReconsent=false"
    )
    sess.cookies.set("OptanonConsent", consent)

def get_session() -> requests.Session:
    s = requests.Session()
    # browsernahe Header
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/140.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    # Cookies einspielen
    cookies = _parse_cookie_string(_read_cookie_string())
    for k, v in cookies.items():
        s.cookies.set(k, v)
    # Notfall: Consent legen, falls er nicht im Cookie vorhanden ist
    if "OptanonConsent" not in s.cookies or "OptanonAlertBoxClosed" not in s.cookies:
        _maybe_set_consent_cookies(s)
    return s

def have_cookie() -> bool:
    return bool(_read_cookie_string())

def warmup(sess: requests.Session, league_id: str):
    """
    Sorgt dafür, dass SSO/Tracking aufgewärmt wird, bevor wir die Draftseite holen.
    """
    # 1) myleagues
    sess.get("https://fantasy.nfl.com/myleagues", timeout=30, allow_redirects=True)
    # 2) irgendeine League-Seite (history landing)
    sess.get(f"https://fantasy.nfl.com/league/{league_id}/history", timeout=30, allow_redirects=True)
    # 3) kleine Pause schadet nicht
    time.sleep(0.5)

def looks_unauth(html: str) -> bool:
    t = html.lower()
    # Heuristik auf gängigen Login/Consent-Strings
    need = ("sign in" in t) or ("signin" in t) or ("login" in t) or ("onetrust" in t) or ("consent" in t)
    # „account“/„id.nfl.com“-Hinweise deuten auch auf Redirectseiten hin
    return need
