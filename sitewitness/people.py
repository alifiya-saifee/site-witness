"""People: who may use the hub, and with which role. Data, not code.

- Kept in run/people.json on this Mac (never committed). The first run has nobody: the Mac page asks for the
  owner's name.
- Roles are a setting (ROLES). Code only ever checks a person's role, never their name.
- PEOPLE is changed in place, so every module that imported it sees the same people.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "run" / "people.json"
ROLES = ("owner", "broker", "engineer", "visitor")

PEOPLE: dict[str, dict] = {}


class PeopleError(ValueError):
    pass


def load() -> None:
    PEOPLE.clear()
    try:
        data = json.loads(FILE.read_text())
    except (OSError, ValueError):
        return
    for pid, p in (data.get("people") or {}).items():
        if isinstance(p, dict) and p.get("role") in ROLES and p.get("name"):
            PEOPLE[pid] = {"name": str(p["name"]), "role": p["role"], "email": str(p.get("email") or "")}


def save() -> None:
    FILE.parent.mkdir(exist_ok=True)
    FILE.write_text(json.dumps({"people": PEOPLE}, ensure_ascii=False, indent=1))
    FILE.chmod(0o600)


def needs_setup() -> bool:
    return not any(p["role"] == "owner" for p in PEOPLE.values())


def owner_id() -> str | None:
    return next((k for k, p in PEOPLE.items() if p["role"] == "owner"), None)


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20] or "person"
    pid, n = base, 2
    while pid in PEOPLE:
        pid, n = f"{base}-{n}", n + 1
    return pid


def add(name: str, role: str, email: str = "") -> str:
    name, email = " ".join(str(name).split())[:60], str(email).strip()[:120]
    if not name:
        raise PeopleError("Type a name")
    if role not in ROLES:
        raise PeopleError("Pick a role")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise PeopleError("That email doesn't look right")
    pid = _slug(name)
    PEOPLE[pid] = {"name": name, "role": role, "email": email}
    save()
    return pid


def remove(pid: str) -> dict:
    p = PEOPLE.get(pid)
    if p is None:
        raise PeopleError("Not a person here")
    if p["role"] == "owner" and sum(q["role"] == "owner" for q in PEOPLE.values()) == 1:
        raise PeopleError("Keep at least one owner")
    del PEOPLE[pid]
    save()
    return p


def public() -> list[dict]:
    return [{"id": k, "name": p["name"], "role": p["role"]} for k, p in PEOPLE.items()]
