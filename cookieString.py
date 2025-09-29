# cookieString.py
import os

def parse_cookie_string(s: str):
    jar = {}
    for part in s.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    return jar

# Erst Secret, sonst Fallback auf lokale Dev-Variable
_cookie = os.getenv("COOKIE_STRING", "")
cookies = parse_cookie_string(_cookie)
