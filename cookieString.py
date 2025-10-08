# cookieString.py
# Liefert ein RequestsCookieJar namens `cookies` und bei Bedarf eine Session mit Headers.
# Quelle des Cookies:
#   - ENV: NFL_COOKIE (empfohlen; in GitHub Actions als Secret setzen)
#   - Fallback: ./data/nfl_cookie.txt (lokal; nicht committen)
# Erkennt versehentlich eingefügte curl-Zeilen (-b "...") und normalisiert Windows-^ Escapes.

from __future__ import annotations
import os, re
from pathlib import Path
from http.cookies import SimpleCookie
import requests

DEFAULT_DOMAIN = ".nfl.com"
COOKIE_ENV_VAR = "NFL_COOKIE"
COOKIE_FILE = Path("data/nfl_cookie.txt")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
}

def _normalize_windows_curl_cookie(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    if s.startswith('^"') and s.endswith('^"'):
        s = s[2:-2]
    s = s.replace("^^", "^").replace('^"', '"').replace("^%", "%").replace("^&", "&")
    return " ".join(s.split())

def _extract_cookie_from_curl(cmd: str) -> str | None:
    if not cmd:
        return None
    text = _normalize_windows_curl_cookie(cmd)
    m = re.search(r'(?:\s-b|\s--cookie)\s+"([^"]+)"', text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'(?:\s-b|\s--cookie)\s+([^\s].+)', text, flags=re.IGNORECASE)
    if m2:
        chunk = m2.group(1).strip()
        chunk = re.split(r'\s+-[HXb-]\b', chunk, maxsplit=1)[0].strip()
        return chunk
    return None

def _load_cookie_header() -> str:
    raw = (os.getenv(COOKIE_ENV_VAR, "") or "").strip()
    if not raw and COOKIE_FILE.exists():
        raw = COOKIE_FILE.read_text(encoding="utf-8", errors="ignore")

    if not raw:
        return ""

    if raw.lstrip().lower().startswith("curl ") or " -b " in raw or " --cookie " in raw:
        extracted = _extract_cookie_from_curl(raw)
        if extracted:
            return extracted

    if "^" in raw:
        raw = _normalize_windows_curl_cookie(raw)

    return raw.strip()

def cookiejar_from_header(header_cookie: str, domain: str = DEFAULT_DOMAIN) -> requests.cookies.RequestsCookieJar:
    jar = requests.cookies.RequestsCookieJar()
    if not header_cookie:
        return jar
    c = SimpleCookie()
    c.load(header_cookie)
    for k, morsel in c.items():
        jar.set(k, morsel.value, domain=domain, path="/")
    return jar

def get_session(headers: dict | None = None, domain: str = DEFAULT_DOMAIN) -> requests.Session:
    sess = requests.Session()
    sess.headers.update(DEFAULT_HEADERS)
    if headers:
        sess.headers.update(headers)
    header_cookie = _load_cookie_header()
    if header_cookie:
        sess.cookies = cookiejar_from_header(header_cookie, domain=domain)
    return sess

def have_cookie() -> bool:
    return bool(_load_cookie_header())

# Export: dein Code importiert `cookies`
cookies = cookiejar_from_header(_load_cookie_header(), domain=DEFAULT_DOMAIN)

