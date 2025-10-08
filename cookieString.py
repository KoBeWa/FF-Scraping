# cookieString.py
import os, requests, pathlib

def _read_cookie_string() -> str:
    # 1) Env
    val = os.getenv("NFL_COOKIE", "").strip()
    if val:
        return val
    # 2) Datei
    p = pathlib.Path("data/nfl_cookie.txt")
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""

def _parse_cookie_string(s: str) -> dict:
    jar = {}
    # Entferne evtl. führendes "Cookie:" falls versehentlich mitkopiert
    if s.lower().startswith("cookie:"):
        s = s.split(":", 1)[1].strip()
    # Split per Semikolon
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    return jar

def get_session() -> requests.Session:
    s = requests.Session()
    # Browsernahe Header (verringert Consent-/Bot-Wände)
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })

    cookie_str = _read_cookie_string()
    cookies = _parse_cookie_string(cookie_str)
    if cookies:
        for k, v in cookies.items():
            # Domain leer lassen → Requests sendet Cookie an Host der jeweiligen URL.
            s.cookies.set(k, v)
    return s

def have_cookie() -> bool:
    return bool(_read_cookie_string())
