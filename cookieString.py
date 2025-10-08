# cookieString.py
import os, requests

def parse_cookie_string(s: str) -> dict:
    jar = {}
    # Zerlege "k=v; k2=v2; ..."
    for part in s.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        jar[k.strip()] = v.strip()
    return jar

def load_cookie_string() -> str:
    env = os.getenv("NFL_COOKIE", "").strip()
    if env:
        return env
    # Fallback: Datei data/nfl_cookie.txt
    p = os.path.join("data", "nfl_cookie.txt")
    if os.path.exists(p):
        return open(p, "r", encoding="utf-8").read().strip()
    return ""

def get_session() -> requests.Session:
    s = requests.Session()
    # realistischere Header
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                  "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    ck = load_cookie_string()
    if ck:
        s.cookies.update(parse_cookie_string(ck))
    return s

def have_cookie() -> bool:
    return bool(load_cookie_string())

    })
    return s

__all__ = ["get_session", "have_cookie", "get_cookie"]
