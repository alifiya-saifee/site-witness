"""Your websites: a short list the owner keeps on the Mac (run/sites.json, never committed).

The agent only ever opens an address from this list. A site can be added:
- on the Mac page (Websites card), or
- by voice: "open Cosmique website" -> "What's the address?" -> "https cosmique dot com" -> the address is read
  back and saved only after the owner taps Approve (so a misheard address is never saved or opened unseen).
Only https addresses, with no password, token or other secret in them.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .records import ROOT

SITES_FILE = ROOT / "run" / "sites.json"
SECRET_PARAMS = re.compile(r"(?:^|[?&#;])(?:token|key|apikey|api_key|password|pass|pwd|secret|session|auth)=", re.I)


class SiteError(ValueError):
    pass


def check_url(url: str) -> str:
    """A safe https address, tidied; or why not."""
    u = str(url or "").strip()
    if not u.lower().startswith("https://"):
        raise SiteError("Only https:// addresses can be saved")
    parts = urlsplit(u)
    host = (parts.hostname or "").lower()
    if parts.username or parts.password:
        raise SiteError("The address can't contain a username or password")
    if not re.fullmatch(r"(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}", host):
        raise SiteError("That doesn't look like a web address (e.g. https://example.com)")
    if SECRET_PARAMS.search(u) or len(u) > 300 or re.search(r"[\s<>\"'`]", u):
        raise SiteError("The address can't contain a token, password or spaces")
    return f"https://{host}{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")


SPOKEN = [(r"\bcolon\b", ":"), (r"\bslash\b", "/"), (r"\bdot\b", "."), (r"\bdash\b|\bhyphen\b", "-"),
          (r"\bنقطة\b", "."), (r"\bشرطة\b", "-")]


def from_speech(said: str) -> str | None:
    """'https cosmique dot com' / 'www.cosmique.ae' / 'cosmique dot com slash about' -> https://… or None."""
    t = str(said or "").strip().lower()
    t = re.sub(r"^(?:it'?s|it is|the address is|address|url|هو|العنوان)\s*:?\s*", "", t)
    for pat, rep in SPOKEN:
        t = re.sub(pat, rep, t)
    t = re.sub(r"\bh\s*t\s*t\s*p\s*s?\b", " ", t)          # "https" / "h t t p s": we always use https
    t = re.sub(r"\bw\s*w\s*w\b", "www", t)
    t = re.sub(r"\s*([./:-])\s*", r"\1", t)                 # "cosmique . com" -> "cosmique.com"
    t = re.sub(r"\s+", "", t).lstrip(":/")                   # what's left of "https://"
    t = re.sub(r"\.{2,}", ".", t).strip(".")
    if not re.search(r"[a-z0-9-]+\.[a-z]{2,}", t):
        return None
    try:
        return check_url("https://" + t)
    except SiteError:
        return None


def load() -> list[dict]:
    try:
        rows = json.loads(SITES_FILE.read_text())
        return [r for r in rows if r.get("id") and r.get("url")]
    except (OSError, ValueError):
        return []


def save(rows: list[dict]) -> None:
    SITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SITES_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1))


def clean_name(text: str, n: int = 40) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s'&.-]", "", str(text or ""))).strip()[:n]


def add(name: str, url: str, words=()) -> dict:
    name = clean_name(name)
    if not name:
        raise SiteError("Give the website a name, e.g. Cosmique website")
    url = check_url(url)
    words = [w for w in (clean_name(x, 30).lower() for x in words) if w]
    base = name.lower().replace(" website", "").replace(" site", "").strip()
    row = {"id": "site-" + uuid.uuid4().hex[:8], "name": name, "url": url,
           "words": list(dict.fromkeys([name.lower(), base] + words))}
    rows = [r for r in load() if r["name"].lower() != name.lower()] + [row]
    save(rows)
    return row


def remove(site_id: str) -> bool:
    rows = load()
    left = [r for r in rows if r["id"] != site_id]
    save(left)
    return len(left) != len(rows)


def get(site_id: str) -> dict | None:
    return next((r for r in load() if r["id"] == site_id), None)


def hint_words() -> list[str]:
    """Names to help Whisper spell them right."""
    return [r["name"] for r in load()]
