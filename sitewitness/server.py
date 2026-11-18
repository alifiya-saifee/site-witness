"""The hub: the control page, pairing, commands, approvals, and the line to the helper.

Run:  python -m sitewitness.server     (or ./run-demo, which also starts the helper)

Safety rules this file keeps:
- A phone or browser on the Wi-Fi must join with the 6-digit pairing code shown on the Mac.
  A browser on the Mac itself (localhost) is trusted without the code.
- Only a helper on this Mac, holding the helper token, can connect, and only it can download files.
- Each file download needs a one-time token tied to one command and one file.
- "Send" never sends: it creates an approval, and even an approved send is only logged in this demo.
- A repeated tap (same key) returns the first result; the file is not opened twice.
- Devices: only ones a person added on the Mac (or the lamp), only the actions their kind allows, only for the
  roles ticked when adding. Printing and risky devices (heat, motion) always wait for an Approve tap.
- Scanning the Wi-Fi and adding or removing devices work only from the Mac itself.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import time
import os
import re
import subprocess
import secrets
import socket
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response

from . import apps, bluetooth, devices, discover, library, mac_map, sites, speech, understand, voice
from .connectors import ir_blaster, roborock_vac
from .commands import parse
from .devices import may_use
from .replies import lang_of, reply
from .events import EventLog
from .records import BY_ID, PEOPLE, RECORDS, ROOT, allowed

RUN_DIR = ROOT / "run"
WEB = ROOT / "web"
PORT = int((os.environ.get("SW_PORT") or "8040"))              # http, this Mac only (page + helper)
SECURE_PORT = int((os.environ.get("SW_SECURE_PORT") or "8443"))  # https, for phones on the Wi-Fi (mic needs https)
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


class Hub:
    def __init__(self, db_path: str = ":memory:"):
        self.log = EventLog(db_path)
        self.pair_code = os.environ.get("SW_PAIR_CODE") or f"{secrets.randbelow(10**6):06d}"
        self.helper_token = secrets.token_urlsafe(24)
        self.sessions: dict[str, dict] = {}     # session token -> {name, at, ip}
        self.pair_fails: dict[str, list[float]] = {}  # device address -> times of wrong codes
        self.pair_fail_total = 0
        self.library: library.Library | None = None
        self.pending: dict[str, dict] = {}       # a question asked back, per device ("What's the address?")
        self.helper: WebSocket | None = None
        self.results: dict[str, dict] = {}       # tap key -> first answer
        self.commands: dict[str, dict] = {}      # command id -> state, detail, proof
        self.file_tokens: dict[str, str] = {}    # one-time download token -> file id
        self.approvals: dict[str, dict] = {}
        self.replies: dict[str, dict] = {}       # reply id -> text, lang, audio, engine, note
        self.reply_tokens: dict[str, str] = {}   # one-time token for the helper to fetch a reply's audio
        self.tasks: set = set()                  # background jobs (speaking on the Mac), kept so they finish
        self.device_state: dict[str, bool] = {}  # last state each device reported (from the helper)
        self.found: dict[str, dict] = {}         # the last Wi-Fi scan: key -> what was found
        self.robot_state: dict[str, dict] = {}   # last state each robot reported: state, battery, place
        self.mac_apps: set[str] = set()          # the live map of apps installed on the Mac (names, from the helper)
        self.finds: dict[str, asyncio.Future] = {}  # file searches waiting for the helper's answer
        self.memory: dict[str, list[dict]] = {}  # per phone / the Mac: the last few turns (memory only, never saved)
        self.plans: dict[str, dict] = {}         # several steps from one sentence, run in order


hub = Hub()
app = FastAPI(title="Site Witness hub (helper demo)")


def is_local(host: str | None) -> bool:
    return (host or "") in LOCAL_HOSTS


def who(request: Request, session: str | None) -> str:
    """Let the request through if it is from this Mac or carries a paired session."""
    if is_local(request.client.host if request.client else None):
        return "this Mac"
    if session and session in hub.sessions:
        return "paired device"
    raise HTTPException(401, "Join with the pairing code first")


@app.get("/")
def page():
    return FileResponse(WEB / "control.html")


@app.get("/api/info")
def info(request: Request, x_session: str | None = Header(default=None)):
    local = is_local(request.client.host if request.client else None)
    return {"local": local, "paired": local or (x_session in hub.sessions),
            "helper": hub.helper is not None,
            "people": [{"id": k, **v} for k, v in PEOPLE.items()]}


@app.post("/api/pair")
async def pair(request: Request):
    """Join with the code. 5 wrong tries from one device lock it for a minute; 20 wrong in all make a new code."""
    ip = request.client.host if request.client else "?"
    now = time.monotonic()
    fails = [t for t in hub.pair_fails.get(ip, []) if now - t < 60]
    hub.pair_fails[ip] = fails
    if len(fails) >= 5:
        hub.log.append("pairing.locked", actor="device", content={"from": ip}, key=f"lock:{ip}:{int(fails[0])}")
        raise HTTPException(429, "Too many wrong codes. Wait a minute, then try again.")
    body = await request.json()
    if not secrets.compare_digest(str(body.get("code", "")).strip(), hub.pair_code):
        fails.append(now)
        hub.pair_fail_total += 1
        hub.log.append("pairing.failed", actor="device", content={"from": ip})
        if hub.pair_fail_total >= 20:
            new_code("too many wrong codes")
        raise HTTPException(403, "That code is not right. It is shown in the terminal on the Mac.")
    hub.pair_fails.pop(ip, None)
    token = secrets.token_urlsafe(18)
    agent = request.headers.get("user-agent", "")
    name = next((n for k, n in (("iPhone", "iPhone"), ("Android", "Android phone"), ("iPad", "iPad"),
                                ("Macintosh", "Mac browser"), ("Windows", "Windows PC")) if k in agent), "Browser")
    hub.sessions[token] = {"name": name, "at": time.strftime("%H:%M"), "ip": ip}
    hub.log.append("pairing.joined", actor="device", content={"from": ip, "device": name})
    return {"session": token}


def new_code(why: str) -> None:
    hub.pair_code = f"{secrets.randbelow(10**6):06d}"
    hub.pair_fail_total = 0
    hub.log.append("pairing.code_changed", actor="hub", content={"why": why})
    print(f"\n  New pairing code ({why}): {hub.pair_code}\n", flush=True)


def session_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:8]  # never show the token itself


@app.get("/api/sessions")
def sessions_list(request: Request):
    mac_only(request)
    return [{"id": session_id(t), **v} for t, v in hub.sessions.items()]


@app.delete("/api/sessions/{sid}")
def sessions_remove(sid: str, request: Request):
    mac_only(request)
    gone = [t for t in hub.sessions if session_id(t) == sid]
    if not gone:
        raise HTTPException(404, "Not a joined device")
    for t in gone:
        info = hub.sessions.pop(t)
        hub.log.append("pairing.removed", actor="owner", content={"device": info["name"], "from": info["ip"]})
    return {"status": "removed"}


@app.post("/api/sessions/reset")
def sessions_reset(request: Request):
    """Log every joined device out and make a new code."""
    mac_only(request)
    n = len(hub.sessions)
    hub.sessions.clear()
    hub.log.append("pairing.removed", actor="owner", content={"device": f"all ({n})"})
    new_code("the owner asked")
    return {"status": "reset", "removed": n}


@app.post("/api/command")
async def command(request: Request, x_session: str | None = Header(default=None)):
    device = who(request, x_session)
    body = await request.json()
    said, person, key = str(body.get("text", "")).strip(), body.get("person", "visitor"), body.get("key")
    choose = body.get("choose")
    if not said:
        raise HTTPException(400, "Say or type a command")
    if person not in PEOPLE:
        raise HTTPException(400, "Unknown person")
    if key and key in hub.results:
        return hub.results[key] | {"repeat": True}
    lang = lang_of(said, body.get("lang"))
    asker = "mac" if device == "this Mac" else f"s:{session_id(x_session or '')}"
    answer = await run_command(said, person, device, key, choose, lang, bool(body.get("also_mac")), asker)
    if key:
        hub.results[key] = answer
    return answer


# ---------------- spoken replies ----------------

async def new_reply(outcome: str, lang: str, also_mac: bool, text: str | None = None, **kw) -> dict:
    """Make the sentence the agent says back (a fixed one for this outcome, or `text`). The audio is made when
    first asked for (and cached). With also_mac, the helper plays it through the Mac's speakers too."""
    rid = uuid.uuid4().hex[:10]
    hub.replies[rid] = {"text": text or reply(outcome, lang, **kw), "lang": lang, "audio": None, "engine": None, "note": None}
    if also_mac:  # in the background: making the audio takes a moment, and nothing should wait for it
        task = asyncio.create_task(say_on_mac(rid))
        hub.tasks.add(task)
        task.add_done_callback(hub.tasks.discard)
    return {"id": rid, "text": hub.replies[rid]["text"], "lang": lang}


async def reply_audio(rid: str) -> dict:
    r = hub.replies[rid]
    if r["audio"] is None:
        r["audio"], r["engine"], r["note"] = await asyncio.to_thread(voice.speak, r["text"], r["lang"])
    return r


async def say_on_mac(rid: str) -> None:
    if hub.helper is None:
        return
    await reply_audio(rid)  # make it before asking, so the Mac speaks without a gap
    token = secrets.token_urlsafe(18)
    hub.reply_tokens[token] = rid
    await hub.helper.send_json({"type": "speak", "reply_id": rid, "token": token})


FILE_WORDS = ("file", "files", "report", "slides", "deck", "document", "pdf", "quote", "note", "notes", "letter",
              "invoice", "contract", "ملف", "تقرير", "عرض", "ملاحظة", "مستند", "فاتورة", "عقد")


async def understood(said: str, spoke_from: str, asker: str = "mac") -> tuple:
    """Groq first (if switched on), the word matcher as backup.
    Returns (steps, answer, how, skipped): a list of Intents, a spoken answer ("" if none)."""
    devs = devices.current()
    words = parse(said, devs, spoke_from)
    if not understand.enabled():
        return [words], "", "word match", 0
    g = await asyncio.to_thread(understand.understand_plan, commands_fix(said), devs, spoke_from,
                                tuple(sorted(hub.mac_apps)), recent_for(asker))
    definite = bool(words.kind or words.action in ("app", "site", "mac_volume", "send") or words.matches or words.search_mode)
    if g is not None:
        steps, answer, skipped = g
        if any(i.action != "unclear" for i in steps) or (answer and not steps):
            return steps, answer, "Groq", skipped
    if definite:
        return [words], "", "word match", 0
    if g is not None:  # Groq wasn't sure either: ask back
        return g[0], g[1], "Groq", g[2]
    return [words], "", "word match", 0


def commands_fix(said: str) -> str:
    from .commands import fix_hearing
    return fix_hearing(said)


# ---------------- memory of the conversation (per phone / the Mac; in memory only, never saved) ----------------

MEMORY_TURNS, MEMORY_FOR = 6, 600.0


def recent_for(asker: str) -> list[str]:
    turns = hub.memory.get(asker, [])
    if turns and time.monotonic() - turns[-1]["at"] > MEMORY_FOR:  # 10 minutes of silence: forget
        hub.memory.pop(asker, None)
        return []
    return [f"said: {t['said']} -> {t['did']}" for t in turns]


def remember(asker: str, said: str, did: str, key: str | None = None) -> None:
    """Add a turn (or update the turn with the same key: a list of steps that went on after a tap)."""
    turns = hub.memory.setdefault(asker, [])
    if key:
        turns[:] = [t for t in turns if t.get("key") != key]
    turns.append({"at": time.monotonic(), "said": said[:200], "did": did[:300], "key": key})
    del turns[:-MEMORY_TURNS]


def describe(intent, ids: bool = False) -> str:
    """What a step is, in a few words. With ids (for memory, so Groq knows what "it" is) the file id is added.
    Names only, never contents."""
    a = intent.action
    if a == "app":
        return f"open {apps.APPS[intent.app].name} on the {intent.target}" + (" with a draft" if intent.message else "")
    if a == "mac_app":
        return f"open {intent.mac_app} on the Mac"
    if a == "mac_volume":
        return {"up": "turn the Mac's volume up", "down": "turn the Mac's volume down", "mute": "mute the Mac",
                "unmute": "unmute the Mac"}.get(intent.volume_op, f"set the Mac's volume to {intent.level}")
    if a == "site":
        s = sites.get(intent.site)
        return f"open {s['name'] if s else 'a website'} on the {intent.target}"
    if a == "site_unknown":
        return f"open {intent.site_name} (not saved yet)"
    if a == "status":
        return {"mac_volume": "check the Mac's volume", "devices": "check the devices", "websites": "list your websites",
                "apps": "list the Mac's apps", "files": "list your files", "history": "say what we just did"}[intent.what]
    if a == "forget":
        return "forget the conversation"
    if a == "unclear":
        return "ask what you meant"
    if intent.kind:
        dev = intent.device
        return f"{say_action(a)} {dev.name if dev else 'the ' + (intent.kind or 'device')}" + \
            (f" ({intent.place})" if intent.place else "")
    files = ", ".join(f"{r.title} [{r.id}]" if ids else r.title for r in intent.matches[:1])
    if a == "send":
        return f"send {files or 'a file'} to {intent.recipient or 'someone'}"
    if intent.search:
        return f"{'find' if intent.search_mode == 'find' else 'open'} files about “{intent.search}”"
    return f"open {files}" if files else "open a file"


def outcome_of(res: dict) -> str:
    """The last thing that happened, from a result's steps."""
    st = res.get("steps") or []
    return st[-1]["t"] if st else res.get("status", "")


async def run_command(said: str, person: str, device: str, key: str | None, choose: str | None,
                      lang: str = "en", also_mac: bool = False, asker: str = "mac") -> dict:
    name = PEOPLE[person]["name"]
    hub.log.append("command.heard", actor=name, content={"said": said, "device": device},
                   key=f"heard:{key}" if key else None)
    steps = [{"t": f"Heard “{said}”", "ok": True}]
    pending = hub.pending.get(asker)
    if pending and time.monotonic() - pending["at"] < 120 and not choose:
        return await answer_question(pending, asker, said, person, steps, lang, also_mac)
    hub.pending.pop(asker, None)
    spoke_from = "mac" if device == "this Mac" else "phone"
    if choose:
        plan, answer, how, skipped = [parse(said, spoke_from=spoke_from)], "", "word match", 0
    else:
        plan, answer, how, skipped = await understood(said, spoke_from, asker)
    steps.append({"t": f"Understood by {how}", "ok": True})
    hub.log.append("command.understood", actor="hub",
                   content={"how": how, "action": plan[0].action if plan else "answer", "steps": str(len(plan))})
    if not plan:  # a question or something not on the menu: just an answer, nothing done
        hub.log.append("answer.given", actor="hub", content={"how": how})
        remember(asker, said, f"answered: {answer}")
        return {"status": "answer", "steps": steps + [{"t": "Answer only: nothing was done", "ok": None}],
                "reply": await new_reply("not_understood", lang, also_mac, text=answer)}
    if len(plan) == 1 and not answer and not skipped:
        res = await do_intent(plan[0], said, person, steps, lang, also_mac, asker, choose)
        if plan[0].action != "forget":
            remember(asker, said, f"{describe(plan[0], ids=True)}: {outcome_of(res)}")
        return res
    return await start_plan(plan, answer, skipped, said, person, steps, lang, also_mac, asker)


async def do_intent(intent, said: str, person: str, steps: list, lang: str, also_mac: bool, asker: str,
                    choose: str | None = None) -> dict:
    """Act on one understood step. Every rule (roles, taps, checks, proof) is applied here."""
    name = PEOPLE[person]["name"]
    if intent.action == "app":
        return await run_app(intent, person, steps, lang, also_mac)
    if intent.action == "mac_app":
        return await run_mac_app(intent.mac_app, person, steps, lang, also_mac)
    if intent.action == "mac_volume":
        return await run_mac_volume(intent, person, steps, lang, also_mac)
    if intent.action == "site":
        return await run_site(intent.site, intent.target, person, steps, lang, also_mac)
    if intent.action == "site_unknown":
        return await ask_for_address(intent, asker, person, steps, lang, also_mac)
    if intent.action == "status":
        return await run_status(intent.what, person, steps, lang, also_mac, asker)
    if intent.action == "forget":
        hub.memory.pop(asker, None)
        hub.log.append("memory.cleared", actor=name, content={})
        return {"status": "answer", "steps": steps + [{"t": "Forgot the recent conversation", "ok": True}],
                "reply": await new_reply("forgot", lang, also_mac)}
    if intent.action == "unclear":
        rep = await new_reply("ask_back", lang, also_mac, q=intent.question) if intent.question and lang == "en" \
            else await new_reply("not_understood", lang, also_mac)
        return {"status": "not_found", "steps": steps + [{"t": "Not sure what you meant", "ok": None}], "reply": rep}
    if intent.kind:
        dev = devices.by_id(choose[4:]) if choose and choose.startswith("dev:") else intent.device
        return await run_device(intent, dev, person, steps, lang, also_mac, choose)
    if choose and choose.startswith("lib:") and choose[4:].isdigit():
        return await open_shared(int(choose[4:]), person, steps, lang, also_mac)
    if choose and choose.startswith("mac:"):
        return await open_found(choose[4:], person, steps, lang, also_mac)
    matches = [BY_ID[choose]] if choose in BY_ID else intent.matches
    if intent.search_mode or (not matches and intent.action == "open"):
        found = await search_shared(intent, person, steps, lang, also_mac)
        from .commands import any_of
        asked_for_files = bool(intent.search) or any_of(intent.text, FILE_WORDS)  # never search the Mac for any sentence
        if PEOPLE[person]["role"] == "owner" and asked_for_files and (found is None or found["status"] == "not_found"):
            on_mac = await search_mac(intent, person, steps, lang, also_mac)
            if on_mac:
                return on_mac
        if found:
            return found
    if not matches:
        hub.log.append("file.not_found", actor="hub", content={"said": said})
        from .commands import any_of
        about_files = any_of(intent.text, FILE_WORDS)  # asked for a file: "couldn't find that file"; else be honest
        return {"status": "not_found",
                "steps": steps + [{"t": "No file in Records matches that" if about_files else "I didn't understand that", "ok": False}],
                "reply": await new_reply("not_found" if about_files else "not_understood", lang, also_mac)}
    if len(matches) > 1:
        hub.log.append("file.ambiguous", actor="hub", content={"options": [r.id for r in matches]})
        return {"status": "choose", "steps": steps + [{"t": f"{len(matches)} files match. Which one?", "ok": None}],
                "options": [{"id": r.id, "title": r.title} for r in matches],
                "reply": await new_reply("choose", lang, also_mac, n=len(matches))}
    rec = matches[0]
    hub.log.append("file.matched", actor="hub", content={"file": rec.id, "title": rec.title})
    steps.append({"t": f"Found “{rec.title}”", "ok": True})
    if not allowed(person, rec):
        hub.log.append("access.refused", actor="hub", content={"file": rec.id, "person": person})
        return {"status": "refused", "steps": steps + [{"t": f"{name} is not allowed to open this file", "ok": False}],
                "reply": await new_reply("refused", lang, also_mac, person=name)}
    steps.append({"t": f"Allowed for {name} ({PEOPLE[person]['role']})", "ok": True})

    if intent.action == "send":
        aid = uuid.uuid4().hex[:10]
        to = intent.recipient or "someone"
        hub.approvals[aid] = {"file": rec.id, "to": to, "by": name, "done": False, "lang": lang, "also_mac": also_mac}
        hub.log.append("approval.requested", actor="hub", content={"approval": aid, "action": "send", "file": rec.id, "to": to})
        return {"status": "needs_approval", "approval": aid, "question": f"Send “{rec.title}” to {to}?",
                "steps": steps + [{"t": "Sending a file needs your tap", "ok": None}],
                "reply": await new_reply("needs_approval", lang, also_mac, file=rec.id, to=to)}

    if hub.helper is None:
        hub.log.append("device.failed", actor="hub", content={"file": rec.id, "why": "no helper connected"})
        return {"status": "no_helper", "steps": steps + [{"t": "No helper is connected on the Mac", "ok": False}],
                "reply": await new_reply("no_helper", lang, False)}
    cid, ftoken = uuid.uuid4().hex[:12], secrets.token_urlsafe(18)
    hub.file_tokens[ftoken] = rec.id
    hub.commands[cid] = {"state": "sent", "detail": "Sent to the Mac", "file": rec.id, "proof": None,
                         "lang": lang, "also_mac": also_mac, "reply": None}
    hub.log.append("device.command", actor="hub", content={"command": cid, "do": "open_file", "file": rec.id})
    await hub.helper.send_json({"type": "open_file", "command_id": cid, "file_id": rec.id,
                                "filename": rec.filename, "token": ftoken})
    # the spoken reply comes with the final result ("Done. … is open."), not now
    return {"status": "sent", "command": cid, "steps": steps + [{"t": "Sent to the Mac", "ok": True}]}


# ---------------- any app on the Mac, files anywhere on the Mac (Owner), questions about live state ----------------

async def run_mac_app(name: str, person: str, steps: list, lang: str, also_mac: bool) -> dict:
    who_ = PEOPLE[person]["name"]
    if not mac_allowed(person):
        hub.log.append("access.refused", actor="hub", content={"app": name, "person": person, "where": "mac"})
        return {"status": "refused", "steps": steps + [{"t": f"{who_} may not open apps on the Mac", "ok": False}],
                "reply": await new_reply("refused_mac_app", lang, also_mac, person=who_)}
    if name not in hub.mac_apps:
        return {"status": "not_found", "steps": steps + [{"t": f"{name} isn't installed on this Mac", "ok": False}],
                "reply": await new_reply("app_not_installed", lang, also_mac, app=name)}
    hub.log.append("app.opened", actor=who_, content={"app": name, "where": "mac", "with_text": "no"})
    return await to_helper({"type": "mac_app", "name": name}, {"app": "mac:" + name, "title": name, "draft": False},
                           steps + [{"t": f"Open {name} on the Mac", "ok": True}], lang, also_mac)


async def find_on_mac(words: str) -> list[dict]:
    """Ask the helper to look through Spotlight (the Mac's own live file index). Names and folder labels only."""
    if hub.helper is None:
        return []
    rid = uuid.uuid4().hex[:12]
    fut = asyncio.get_running_loop().create_future()
    hub.finds[rid] = fut
    await hub.helper.send_json({"type": "find", "request_id": rid, "words": words[:120]})
    try:
        items = await asyncio.wait_for(fut, 8)
    except asyncio.TimeoutError:
        return []
    finally:
        hub.finds.pop(rid, None)
    return [{"id": str(i.get("id", ""))[:12], "name": str(i.get("name", ""))[:120], "folder": str(i.get("folder", ""))[:120]}
            for i in items if isinstance(i, dict) and re.fullmatch(r"[0-9a-f]{12}", str(i.get("id", "")))][:8]


async def search_mac(intent, person: str, steps: list, lang: str, also_mac: bool) -> dict | None:
    """Owner only: search the whole Mac. None if nothing was found (the usual reply follows)."""
    words = intent.search or intent.text
    items = await find_on_mac(words)  # the helper keeps only plain words (mac_map.safe_words)
    hub.log.append("file.searched", actor="hub", content={"mode": "mac", "found": str(len(items))})
    if not items:
        return None
    steps = steps + [{"t": f"Searched the Mac (Spotlight): {len(items)} file(s)", "ok": True}]
    if len(items) == 1 and intent.search_mode != "find":
        return await open_found(items[0]["id"], person, steps, lang, also_mac, items[0]["name"])
    options = [{"id": f"mac:{i['id']}", "title": i["name"], "snippet": i["folder"]} for i in items]
    return {"status": "choose", "steps": steps + [{"t": "Which one?", "ok": None}], "options": options,
            "reply": await new_reply("search_found", lang, also_mac, n=len(items), q=words)}


async def open_found(fid: str, person: str, steps: list, lang: str, also_mac: bool, name: str = "") -> dict:
    if PEOPLE[person]["role"] != "owner":
        who_ = PEOPLE[person]["name"]
        return {"status": "refused", "steps": steps + [{"t": f"Only the owner can open files from the whole Mac", "ok": False}],
                "reply": await new_reply("refused", lang, also_mac, person=who_)}
    if not re.fullmatch(r"[0-9a-f]{12}", fid or ""):
        raise HTTPException(400, "Bad choice")
    return await to_helper({"type": "open_found", "found_id": fid}, {"file": "found", "title": name or "the file"},
                           steps + [{"t": f"Open {name or 'the file you chose'} on the Mac", "ok": True}], lang, also_mac)


def device_line(d, lang: str) -> str:
    if d.kind == "robot":
        r = hub.robot_state.get(d.id) or {}
        st = r.get("state") or ("لم يُستخدم بعد" if lang == "ar" else "not used yet")
    else:
        on = hub.device_state.get(d.id)
        st = ("يعمل" if on else "مطفأ" if on is False else "لم يُستخدم بعد") if lang == "ar" else \
            ("on" if on else "off" if on is False else "not used yet")
    return f"{d.name_ar if lang == 'ar' and d.name_ar else d.name}: {st}"


async def run_status(what: str, person: str, steps: list, lang: str, also_mac: bool, asker: str) -> dict:
    """Questions about live state: read, change nothing."""
    ar = lang == "ar"
    if what == "mac_volume":
        if not mac_allowed(person):
            who_ = PEOPLE[person]["name"]
            return {"status": "refused", "steps": steps + [{"t": f"{who_} may not use the Mac", "ok": False}],
                    "reply": await new_reply("refused_mac_app", lang, also_mac, person=who_)}
        return await to_helper({"type": "mac", "action": "get"}, {"mac": "get"},
                               steps + [{"t": "Read the Mac's volume (nothing changes)", "ok": True}], lang, also_mac)
    if what == "devices":
        devs = [d for d in devices.current() if may_use(person, d)]
        lines = [device_line(d, lang) for d in devs]
        text = ("الأجهزة: " + "، ".join(lines) + ".") if ar else ("Devices: " + "; ".join(lines) + ".") if lines else \
            ("لا توجد أجهزة." if ar else "There are no devices you can use.")
    elif what == "websites":
        names = [s["name"] for s in sites.load()]
        text = (("مواقعك: " + "، ".join(names)) if ar else ("Your websites: " + ", ".join(names) + ".")) if names else \
            ("لا توجد مواقع محفوظة." if ar else "You have no websites saved yet.")
    elif what == "apps":
        names = sorted(hub.mac_apps)
        some = ", ".join(n for n in ("Notes", "Safari", "Mail", "Calendar", "Music", "Photos") if n in hub.mac_apps)
        text = (f"على الماك {len(names)} تطبيقًا." if ar else f"There are {len(names)} apps on the Mac"
                + (f", including {some}." if some else ".")) if names else \
            ("مساعد الماك غير متصل." if ar else "The Mac helper isn't connected, so I can't see its apps.")
    elif what == "files":
        mine = [r.title for r in RECORDS if allowed(person, r)]
        lib = get_library()
        text = ("ملفاتك في السجلات: " + "، ".join(mine)) if ar else \
            ("In Records: " + ", ".join(mine) + "." + (" You can also search the shared folder." if lib else "") +
             (" As the owner, you can ask me to find any file on the Mac." if PEOPLE[person]["role"] == "owner" else ""))
    else:  # history
        turns = recent_for(asker)
        said = [re.sub(r" \[[\w-]+\]", "", t.split(" -> ", 1)[-1]) for t in turns[-3:]]
        text = (("قبل قليل: " if ar else "Just now: ") + " · ".join(said)) if turns \
            else ("لم نتحدث عن شيء بعد." if ar else "We haven't done anything yet in the last 10 minutes.")
    hub.log.append("answer.given", actor="hub", content={"about": what})
    return {"status": "answer", "steps": steps + [{"t": text, "ok": True}],
            "reply": await new_reply("not_understood", lang, also_mac, text=text[:400])}


# ---------------- several steps from one sentence ----------------

FINAL = ("confirmed", "unconfirmed", "failed")
PLAIN = {"done": "done", "unsure": "done (not checked)", "failed": "failed", "skipped": "not done",
         "needs_approval": "waiting for your tap", "waiting": "not started", "phone": "button on the phone",
         "question": "waiting for your answer", "choose": "waiting for you to pick one"}
STATE_WORDS = {"done": "done", "unsure": "done, but it couldn't be checked", "failed": "FAILED",
               "skipped": "NOT done (skipped)", "needs_approval": "NOT done yet: waiting for the person to tap Approve",
               "waiting": "NOT started yet", "phone": "ready as a button to tap on the phone",
               "question": "NOT done yet: waiting for the person's answer", "choose": "NOT done yet: they must pick one"}
NOT_YET = re.compile(r"\b(sent|printed|emailed|is cleaning|started cleaning|on its way)\b|أُرسل|أرسلت|تم إرسال|تم الإرسال|طُبع|تمت الطباعة",
                     re.I)


def public_plan(p: dict) -> dict:
    out = {"id": p["id"], "state": p["state"], "reply": p.get("reply"), "answer": p.get("answer") or "", "steps": []}
    for s in p["steps"]:
        row = {k: s[k] for k in ("label", "state", "detail", "approval", "question", "link", "app", "options") if s.get(k)}
        if s.get("command") and hub.commands.get(s["command"], {}).get("proof"):
            row["proof"] = s["command"]
        out["steps"].append(row)
    return out


async def start_plan(plan, answer: str, skipped: int, said: str, person: str, steps: list, lang: str,
                     also_mac: bool, asker: str) -> dict:
    pid = uuid.uuid4().hex[:10]
    p = {"id": pid, "said": said, "person": person, "lang": lang, "also_mac": also_mac, "asker": asker,
         "intents": plan, "answer": answer, "state": "running", "reply": None,
         "steps": [{"label": describe(i), "memo": describe(i, ids=True), "state": "waiting"} for i in plan] +
                  [{"label": "A step I couldn't match to anything I can do", "state": "skipped"}] * skipped}
    hub.plans[pid] = p
    hub.log.append("plan.started", actor=PEOPLE[person]["name"], content={"plan": pid, "steps": str(len(plan))})
    task = asyncio.create_task(run_plan(pid, 0))
    hub.tasks.add(task)
    task.add_done_callback(hub.tasks.discard)
    return {"status": "plan", "plan": pid, "steps": steps + [{"t": f"{len(plan)} steps, in order", "ok": True}]}


async def wait_for_command(cid: str, limit: float = 75) -> dict:
    until = time.monotonic() + limit
    while time.monotonic() < until:
        c = hub.commands.get(cid)
        if c and c["state"] in FINAL:
            return c
        await asyncio.sleep(0.25)
    return {"state": "failed", "detail": "No answer from the Mac within 75 seconds"}


async def settle_step(p: dict, idx: int, res: dict) -> str:
    """Record one step's result. Returns 'next', 'pause' (waiting for a tap or an answer) or 'stop'."""
    s, status = p["steps"][idx], res.get("status")
    if status == "approved" and res.get("then"):  # after a tap: what the approved action then did
        status = res["then"]
    if status == "sent":
        s["command"] = res["command"]
        s["state"] = "running"
        c = await wait_for_command(res["command"])
        s["detail"] = c.get("detail", "")
        s["state"] = {"confirmed": "done", "unconfirmed": "unsure"}.get(c["state"], "failed")
    elif status == "needs_approval":
        s.update(state="needs_approval", approval=res["approval"], question=res.get("question"))
        hub.approvals[res["approval"]]["plan"] = (p["id"], idx)
        return "pause"
    elif status == "open_on_phone":
        s.update(state="phone", link=res.get("link"), app=res.get("app"), detail=f"Tap to open {res.get('app')}")
    elif status in ("answer", "approved"):
        s.update(state="done", detail=outcome_of(res) if status == "answer" else
                 "Approved by you. Demo only: logged, nothing was really sent")
    elif status == "question":
        s.update(state="question", question=res.get("question"), detail=outcome_of(res))
        return "pause"
    elif status == "choose":
        s.update(state="choose", options=res.get("options"), detail=outcome_of(res))
        return "pause"
    else:  # refused, not found, no helper, failed, cancelled
        s.update(state="failed", detail=outcome_of(res))
    hub.log.append("plan.step", actor="hub", content={"plan": p["id"], "step": str(idx + 1), "state": s["state"]})
    return "stop" if s["state"] == "failed" else "next"


async def run_plan(pid: str, start: int) -> None:
    p = hub.plans[pid]
    p["state"] = "running"
    for idx in range(start, len(p["intents"])):
        if p["state"] == "cancelled":
            return
        p["steps"][idx]["state"] = "running"
        try:
            res = await do_intent(p["intents"][idx], p["said"], p["person"], [], p["lang"], False, p["asker"])
            got = await settle_step(p, idx, res)
        except Exception as e:  # never leave a plan hanging
            p["steps"][idx].update(state="failed", detail=f"Error: {type(e).__name__}")
            got = "stop"
        if got == "pause":
            p["state"] = "waiting"
            await finish_plan(p, waiting=True)
            return
        if got == "stop":
            for s in p["steps"][idx + 1:]:
                if s["state"] == "waiting":
                    s["state"] = "skipped"
            break
    await finish_plan(p)


async def finish_plan(p: dict, waiting: bool = False) -> None:
    """One spoken reply for the whole sentence: written fresh from the real results (fact-checked),
    or a fixed sentence."""
    if not waiting:
        p["state"] = "done"
    done = [s for s in p["steps"] if s["state"] in ("done", "unsure", "phone")]
    failed = next(((i, s) for i, s in enumerate(p["steps"]) if s["state"] == "failed"), None)
    facts = [f"step {i + 1}: {s['label']} -> {STATE_WORDS.get(s['state'], s['state'])}" +
             (f" ({s['detail']})" if s.get("detail") else "") for i, s in enumerate(p["steps"])]
    if p.get("answer"):
        facts.append(f"answer to the question: {p['answer']}")
    names = [a.name for a in apps.APPS.values()] + sorted(hub.mac_apps) + [s["name"] for s in sites.load()] + \
            [d.name for d in devices.current()] + [r.title for r in RECORDS]
    text = await asyncio.to_thread(understand.write_reply, p["lang"], facts, names) if understand.enabled() else None
    not_sent = any(s["state"] in ("needs_approval", "waiting", "skipped") for s in p["steps"]) or \
        any(s["label"].startswith("send ") for s in p["steps"])  # demo: an approved send is only logged
    if text and not_sent and NOT_YET.search(text):
        text = None  # it said "sent" / "printed" for something that didn't happen: use the fixed sentence
    if text is None:
        if failed:
            fixed = ("plan_failed", {"n": failed[0] + 1, "problem": failed[1].get("detail", "")})
        elif waiting:
            fixed = ("plan_waiting", {"n": len(done)}) if done else ("plan_waiting_first", {})
        else:
            fixed = ("plan_done", {"n": len(done)})
        text = reply(fixed[0], p["lang"], **fixed[1])
        if p.get("answer") and not failed:
            text = f"{text} {p['answer']}"
    p["reply"] = await new_reply("plan_done", p["lang"], p["also_mac"], text=text)
    hub.log.append("plan.finished", actor="hub", content={"plan": p["id"], "state": p["state"],
                                                          "done": str(len(done)), "fresh": "no" if text is None else "yes"})
    remember(p["asker"], p["said"], "; ".join(f"{s.get('memo', s['label'])}: {PLAIN.get(s['state'], s['state'])}"
                                              for s in p["steps"]), key=p["id"])


async def resume_plan(aid: str, answer: dict) -> None:
    pid, idx = hub.approvals[aid]["plan"]
    p = hub.plans.get(pid)
    if not p or p["state"] == "cancelled":
        return
    p["state"] = "running"
    p["reply"] = None
    got = await settle_step(p, idx, answer)
    if got == "stop":
        for s in p["steps"][idx + 1:]:
            if s["state"] == "waiting":
                s["state"] = "skipped"
        await finish_plan(p)
        return
    await run_plan(pid, idx + 1)


@app.get("/api/plan/{pid}")
def plan_status(pid: str, request: Request, x_session: str | None = Header(default=None)):
    who(request, x_session)
    p = hub.plans.get(pid)
    if not p:
        raise HTTPException(404, "Unknown plan")
    return public_plan(p)


@app.post("/api/plan/{pid}/cancel")
async def plan_cancel(pid: str, request: Request, x_session: str | None = Header(default=None)):
    who(request, x_session)
    p = hub.plans.get(pid)
    if not p:
        raise HTTPException(404, "Unknown plan")
    if p["state"] in ("done", "cancelled"):
        return public_plan(p)
    p["state"] = "cancelled"
    for s in p["steps"]:
        if s["state"] in ("waiting", "needs_approval", "question", "choose"):
            if s.get("approval") in hub.approvals:
                hub.approvals[s["approval"]]["cancelled"] = True
            s["state"] = "skipped"
    hub.pending.pop(p["asker"], None)
    p["reply"] = await new_reply("plan_cancelled", p["lang"], p["also_mac"])
    hub.log.append("plan.finished", actor="hub", content={"plan": pid, "state": "cancelled"})
    return public_plan(p)


def get_library() -> "library.Library | None":
    """The shared folder's index, if the owner shared a folder (opened once, kept)."""
    st = library.settings()
    if not st:
        if hub.library:
            hub.library.close()
        hub.library = None
        return None
    if hub.library is None or str(hub.library.folder) != str(Path(st["folder"]).resolve()):
        if hub.library:
            hub.library.close()
        hub.library = library.Library(Path(st["folder"]))
    return hub.library


async def search_shared(intent, person: str, steps: list, lang: str, also_mac: bool) -> dict | None:
    """Look inside the shared folder's files. None means: nothing to say here, fall back to Records."""
    lib, st = get_library(), library.settings()
    q = (intent.search or "").strip()
    if lib is None:
        if intent.search_mode:
            return {"status": "not_found", "steps": steps + [{"t": "No folder is shared for searching (Mac → Shared folder)", "ok": False}],
                    "reply": await new_reply("no_folder", lang, also_mac)}
        return None
    if PEOPLE[person]["role"] not in st.get("roles", []):
        name = PEOPLE[person]["name"]
        return {"status": "refused", "steps": steps + [{"t": f"{name} may not open files from the shared folder", "ok": False}],
                "reply": await new_reply("refused", lang, also_mac, person=name)}
    if not library.Library.terms(q):
        return None
    results = await asyncio.to_thread(lib.search, q)
    words = " ".join(library.Library.terms(q)) if lang == "en" else q
    hub.log.append("file.searched", actor="hub", content={"mode": intent.search_mode or "open", "found": str(len(results))})
    if not results:
        if not intent.search_mode:
            return None  # nothing in the folder either: the usual "couldn't find that file"
        return {"status": "not_found", "steps": steps + [{"t": f"No file in the shared folder mentions “{q}”", "ok": False}],
                "reply": await new_reply("search_none", lang, also_mac, q=words)}
    steps = steps + [{"t": f"Searched inside the shared folder: {len(results)} file(s)", "ok": True}]
    clear = len(results) == 1 or results[0]["score"] < results[1]["score"] * 1.5  # bm25: lower is better
    if intent.search_mode != "find" and clear:
        return await open_shared(results[0]["id"], person, steps, lang, also_mac)
    options = [{"id": f"lib:{r['id']}", "title": r["title"], "snippet": r["snippet"]} for r in results]
    rep = await new_reply("search_one", lang, also_mac, q=words, title=results[0]["title"], file="lib") if len(results) == 1 \
        else await new_reply("search_found", lang, also_mac, n=len(results), q=words)
    return {"status": "choose", "steps": steps + [{"t": "Which one?", "ok": None}], "options": options, "reply": rep}


async def open_shared(fid: int, person: str, steps: list, lang: str, also_mac: bool) -> dict:
    lib, st = get_library(), library.settings() or {}
    name = PEOPLE[person]["name"]
    if PEOPLE[person]["role"] not in st.get("roles", []):
        return {"status": "refused", "steps": steps + [{"t": f"{name} may not open files from the shared folder", "ok": False}],
                "reply": await new_reply("refused", lang, also_mac, person=name)}
    path = lib.path_of(fid) if lib else None
    if path is None:
        return {"status": "not_found", "steps": steps + [{"t": "That file isn't in the shared folder any more", "ok": False}],
                "reply": await new_reply("file_gone", lang, also_mac)}
    title = lib.get(fid)["title"]
    steps = steps + [{"t": f"Found “{title}” in the shared folder", "ok": True}]
    if hub.helper is None:
        return {"status": "no_helper", "steps": steps + [{"t": "No helper is connected on the Mac", "ok": False}],
                "reply": await new_reply("no_helper", lang, False)}
    fileid, ftoken, cid = f"lib-{fid}", secrets.token_urlsafe(18), uuid.uuid4().hex[:12]
    hub.file_tokens[ftoken] = fileid
    hub.commands[cid] = {"state": "sent", "detail": "Sent to the Mac", "file": fileid, "title": title, "proof": None,
                         "lang": lang, "also_mac": also_mac, "reply": None}
    hub.log.append("device.command", actor="hub", content={"command": cid, "do": "open_file", "file": fileid})
    await hub.helper.send_json({"type": "open_file", "command_id": cid, "file_id": fileid,
                                "filename": fileid + path.suffix.lower(), "token": ftoken})
    return {"status": "sent", "command": cid, "steps": steps + [{"t": "Sent to the Mac", "ok": True}]}


def mac_allowed(person: str) -> bool:
    return PEOPLE[person]["role"] in ("owner", "broker")  # the Mac is the owner's machine


async def to_helper(msg: dict, entry: dict, steps: list, lang: str, also_mac: bool) -> dict:
    """Send one job to the Mac helper and let the page follow it (status, proof, spoken reply)."""
    if hub.helper is None:
        return {"status": "no_helper", "steps": steps + [{"t": "No helper is connected on the Mac", "ok": False}],
                "reply": await new_reply("no_helper", lang, False)}
    cid = uuid.uuid4().hex[:12]
    hub.commands[cid] = {"state": "sent", "detail": "Sent to the Mac", "proof": None, "lang": lang,
                         "also_mac": also_mac, "reply": None} | entry
    await hub.helper.send_json(msg | {"command_id": cid})
    return {"status": "sent", "command": cid, "steps": steps + [{"t": "Sent to the Mac", "ok": True}]}


async def run_mac_volume(intent, person: str, steps: list, lang: str, also_mac: bool) -> dict:
    name = PEOPLE[person]["name"]
    if not mac_allowed(person):
        return {"status": "refused", "steps": steps + [{"t": f"{name} may not change the Mac's volume", "ok": False}],
                "reply": await new_reply("refused_mac_app", lang, also_mac, person=name)}
    op = intent.volume_op
    label = {"up": "Turn the Mac's volume up", "down": "Turn the Mac's volume down", "mute": "Mute the Mac",
             "unmute": "Unmute the Mac", "set": f"Set the Mac's volume to {intent.level}"}[op]
    hub.log.append("mac.volume", actor=name, content={"op": op, **({"level": str(intent.level)} if op == "set" else {})})
    msg = {"type": "mac", "action": op} | ({"level": intent.level} if op == "set" else {})
    return await to_helper(msg, {"mac": op}, steps + [{"t": label, "ok": True}], lang, also_mac)


async def run_site(site_id: str, target: str, person: str, steps: list, lang: str, also_mac: bool) -> dict:
    site = sites.get(site_id)
    name = PEOPLE[person]["name"]
    if not site:
        return {"status": "not_found", "steps": steps + [{"t": "That website isn't saved any more", "ok": False}],
                "reply": await new_reply("not_understood", lang, also_mac)}
    hub.log.append("site.opened", actor=name, content={"site": site["name"], "where": target})
    if target == "phone":
        return {"status": "open_on_phone", "app": site["name"], "link": site["url"],
                "steps": steps + [{"t": f"Open {site['name']} on this phone", "ok": True}],
                "reply": await new_reply("phone_app", lang, also_mac, app=site["name"])}
    if not mac_allowed(person):
        return {"status": "refused", "steps": steps + [{"t": f"{name} may not open things on the Mac", "ok": False}],
                "reply": await new_reply("refused_mac_app", lang, also_mac, person=name)}
    return await to_helper({"type": "site", "site_id": site_id}, {"app": "site", "title": site["name"], "draft": False},
                           steps + [{"t": f"Open {site['name']} on the Mac", "ok": True}], lang, also_mac)


async def ask_for_address(intent, asker: str, person: str, steps: list, lang: str, also_mac: bool) -> dict:
    """A website that isn't saved: ask for its address (only the owner may add one)."""
    name = intent.site_name or "our website"
    if PEOPLE[person]["role"] != "owner":
        return {"status": "not_found", "steps": steps + [{"t": f"“{name}” isn't saved, and only the owner can add websites", "ok": False}],
                "reply": await new_reply("site_owner_only", lang, also_mac, app=name)}
    hub.pending[asker] = {"kind": "site_url", "name": name, "target": intent.target, "at": time.monotonic(), "tries": 0}
    return {"status": "question", "question": f"What's the address of {name}?",
            "steps": steps + [{"t": f"“{name}” isn't saved yet. Asking for its address", "ok": None}],
            "reply": await new_reply("site_ask_url", lang, also_mac, app=name)}


async def answer_question(pending: dict, asker: str, said: str, person: str, steps: list, lang: str, also_mac: bool) -> dict:
    """The answer to "What's the address?": read it back and ask for one tap before saving."""
    from .commands import any_of, normalise as norm
    if any_of(norm(said), ("cancel", "never mind", "nevermind", "stop", "no", "الغاء", "إلغاء", "لا")):
        hub.pending.pop(asker, None)
        return {"status": "not_found", "steps": steps + [{"t": "Cancelled", "ok": None}],
                "reply": await new_reply("site_cancelled", lang, also_mac)}
    url = sites.from_speech(said)
    if not url:
        pending["tries"] += 1
        if pending["tries"] >= 3:
            hub.pending.pop(asker, None)
        return {"status": "question", "question": f"What's the address of {pending['name']}?",
                "steps": steps + [{"t": "That didn't sound like a web address", "ok": False}],
                "reply": await new_reply("site_bad_url", lang, also_mac)}
    hub.pending.pop(asker, None)
    aid = uuid.uuid4().hex[:10]
    hub.approvals[aid] = {"site_add": True, "name": pending["name"], "url": url, "target": pending["target"],
                          "by": PEOPLE[person]["name"], "person": person, "done": False, "lang": lang, "also_mac": also_mac}
    hub.log.append("approval.requested", actor="hub", content={"approval": aid, "action": "save website", "site": pending["name"]})
    return {"status": "needs_approval", "approval": aid, "question": f"Save “{pending['name']}” as {url} and open it?",
            "steps": steps + [{"t": f"Heard the address as {url}", "ok": True},
                              {"t": "Check the address, then tap Approve to save it", "ok": None}],
            "reply": await new_reply("site_confirm", lang, also_mac, app=pending["name"])}


async def run_app(intent, person: str, steps: list, lang: str, also_mac: bool) -> dict:
    """Open an app from the approved list, on the phone (a one-tap button) or on this Mac (the helper).
    Drafts are typed, never sent: you add who it's to and press send yourself."""
    name, app = PEOPLE[person]["name"], apps.APPS[intent.app]
    title = app.name
    draft = " with your text typed (you press send)" if intent.message else ""
    log = {"app": app.key, "where": intent.target, "with_text": "yes" if intent.message else "no"}  # never the text
    if intent.target == "phone":
        if not app.phone:
            return {"status": "not_found", "steps": steps + [{"t": f"{title} can't be opened on a phone from a web page", "ok": False}],
                    "reply": await new_reply("app_not_on_phone", lang, also_mac, app=title)}
        hub.log.append("app.opened", actor=name, content=log)
        rep = await new_reply(("mail_draft_phone" if app.key == "mail" else "phone_message") if intent.message
                              else "phone_app", lang, also_mac, app=title)
        return {"status": "open_on_phone", "app": title, "link": apps.link(app.key, intent.message),
                "steps": steps + [{"t": f"Open {title} on this phone{draft}", "ok": True}], "reply": rep}
    # the Mac
    if not app.on_mac:
        return {"status": "not_found", "steps": steps + [{"t": f"{title} is only on your phone", "ok": False}],
                "reply": await new_reply("app_not_on_mac", lang, also_mac, app=title)}
    if PEOPLE[person]["role"] not in ("owner", "broker"):  # the Mac is the owner's machine
        hub.log.append("access.refused", actor="hub", content={"app": app.key, "person": person, "where": "mac"})
        return {"status": "refused", "steps": steps + [{"t": f"{name} may not open apps on the Mac", "ok": False}],
                "reply": await new_reply("refused_mac_app", lang, also_mac, person=name)}
    steps = steps + [{"t": f"Open {title} on the Mac{draft}", "ok": True}]
    if hub.helper is None:
        return {"status": "no_helper", "steps": steps + [{"t": "No helper is connected on the Mac", "ok": False}],
                "reply": await new_reply("no_helper", lang, False)}
    cid = uuid.uuid4().hex[:12]
    hub.commands[cid] = {"state": "sent", "detail": "Sent to the Mac", "app": app.key, "title": title,
                         "draft": bool(intent.message), "proof": None, "lang": lang, "also_mac": also_mac, "reply": None}
    hub.log.append("app.opened", actor=name, content=log | {"command": cid})
    msg = {"type": "app", "command_id": cid, "app": app.key}
    if intent.message:
        msg["text"] = intent.message
    await hub.helper.send_json(msg)
    return {"status": "sent", "command": cid, "steps": steps + [{"t": "Sent to the Mac", "ok": True}]}


def say_action(action: str) -> str:
    return {"start": "start cleaning", "clean": "clean", "pause": "pause", "dock": "go home to charge", "goto": "go to",
            "stop": "stop", "volume_up": "volume up", "volume_down": "volume down", "app:youtube": "open YouTube",
            "app:netflix": "open Netflix", "hdmi": "change input", "print": "print", "toggle": "press power on",
            "brighter": "make brighter", "dimmer": "dim", "colour": "change the colour of", "mode": "change the mode of",
            "forward": "roll forward", "back": "roll back", "left": "turn left", "right": "turn right", "spin": "spin",
            "press": "press the switch with"
            }.get(action, f"switch {action}")


async def run_device(intent, dev, person: str, steps: list, lang: str, also_mac: bool, choose: str | None) -> dict:
    name, action = PEOPLE[person]["name"], intent.action
    if dev is None and action == "stop" and intent.kind == "robot" and intent.device_options:
        return await stop_all(intent.device_options, person, steps, lang, also_mac)
    if dev is None:
        if len(intent.device_options) > 1:
            return {"status": "choose", "steps": steps + [{"t": f"{len(intent.device_options)} devices fit. Which one?", "ok": None}],
                    "options": [{"id": "dev:" + d.id, "title": f"{d.name[:1].upper() + d.name[1:]} ({d.room})"}
                                for d in intent.device_options],
                    "reply": await new_reply("choose_device", lang, also_mac, n=len(intent.device_options))}
        hub.log.append("device.failed", actor="hub", content={"kind": intent.kind, "why": "none added"})
        return {"status": "not_found", "steps": steps + [{"t": f"No {intent.kind} is added yet (Scan my Wi-Fi on the Mac)", "ok": False}],
                "reply": await new_reply("no_device", lang, also_mac, kind=intent.kind)}
    if dev.kind == "ir" and action in ("on", "off") and action not in dev.actions and "toggle" in dev.actions:
        action = "toggle"  # one power button on the remote: it switches on and off
    hub.log.append("device.matched", actor="hub", content={"device": dev.id, "action": action})
    steps.append({"t": f"Found “{dev.name}” ({dev.room}): {say_action(action)}", "ok": True})
    if not may_use(person, dev) or action not in dev.actions:
        hub.log.append("access.refused", actor="hub", content={"device": dev.id, "person": person})
        return {"status": "refused", "steps": steps + [{"t": f"{name} is not allowed to use this device", "ok": False}],
                "reply": await new_reply("refused_device", lang, also_mac, person=name, device=dev)}
    steps.append({"t": f"Allowed for {name} ({PEOPLE[person]['role']})", "ok": True})
    rec, place = None, intent.place
    if dev.kind == "robot":
        if action == "stop":  # stop goes first: it never waits for a tap and cancels any waiting robot approvals
            cancel_waiting(dev.id)
            return await send_device(dev, "stop", steps, lang, also_mac)
        if intent.place_unknown:
            return {"status": "not_found", "steps": steps + [{"t": f"{dev.name} has no room called “{intent.place_unknown}”", "ok": False}],
                    "reply": await new_reply("unknown_place", lang, also_mac, device=dev, place=intent.place_unknown,
                                             places=dev.place_names)}
    if action == "print":
        matches = [BY_ID[choose]] if choose in BY_ID else intent.matches
        if not matches:
            return {"status": "not_found", "steps": steps + [{"t": "Which file? No file in Records matches that", "ok": False}],
                    "reply": await new_reply("not_found", lang, also_mac)}
        if len(matches) > 1:
            return {"status": "choose", "steps": steps + [{"t": f"{len(matches)} files match. Which one?", "ok": None}],
                    "options": [{"id": r.id, "title": r.title} for r in matches],
                    "reply": await new_reply("choose", lang, also_mac, n=len(matches))}
        rec = matches[0]
        if not allowed(person, rec):
            hub.log.append("access.refused", actor="hub", content={"file": rec.id, "person": person})
            return {"status": "refused", "steps": steps + [{"t": f"{name} is not allowed to print this file", "ok": False}],
                    "reply": await new_reply("refused", lang, also_mac, person=name)}
        steps.append({"t": f"File: “{rec.title}”", "ok": True})
    if dev.needs_tap_for(action):  # printing, robots moving, risky devices: a person taps Approve first, every time
        aid = uuid.uuid4().hex[:10]
        hub.approvals[aid] = {"device": dev.id, "action": action, "file": rec.id if rec else None, "place": place,
                              "by": name, "done": False, "lang": lang, "also_mac": also_mac}
        hub.log.append("approval.requested", actor="hub",
                       content={"approval": aid, "action": say_action(action), "device": dev.id,
                                **({"file": rec.id} if rec else {}), **({"place": place} if place else {})})
        if rec:
            question, why = f"Print “{rec.title}” on {dev.name}?", "Printing uses paper and can't be undone: it needs your tap"
            rep = await new_reply("approve_print", lang, also_mac, file=rec.id, device=dev)
        elif dev.kind == "robot":
            question = f"{say_action(action).capitalize()}{' the ' + place.lower() if place else ''}: {dev.name}?"
            why = "The robot moves: it needs your tap (Stop never does)"
            rep = await new_reply("approve_robot", lang, also_mac, device=dev, action=action, place=place or "")
        else:
            question, why = f"{say_action(action).capitalize()}: {dev.name}?", "This device heats or moves: it needs your tap"
            rep = await new_reply("approve_device", lang, also_mac, device=dev, action=action)
        return {"status": "needs_approval", "approval": aid, "question": question,
                "steps": steps + [{"t": why, "ok": None}], "reply": rep}
    return await send_device(dev, action, steps, lang, also_mac, place=place)


def cancel_waiting(device_id: str) -> None:
    for aid, a in hub.approvals.items():
        if a.get("device") == device_id and not a["done"]:
            a["done"], a["cancelled"] = True, True
            hub.log.append("approval.cancelled", actor="hub", content={"approval": aid, "device": device_id,
                                                                       "why": "stop was said"})


async def stop_all(robots, person: str, steps: list, lang: str, also_mac: bool) -> dict:
    """"Stop" with no robot named: every robot this person may use stops, now, with no tap."""
    mine = [d for d in robots if may_use(person, d)]
    if not mine:
        return {"status": "refused", "steps": steps + [{"t": "You're not allowed to use these robots", "ok": False}],
                "reply": await new_reply("refused_device", lang, also_mac, person=PEOPLE[person]["name"], device=robots[0])}
    sent = []
    for d in mine:
        cancel_waiting(d.id)
        sent.append(await send_device(d, "stop", [], lang, False))
    cids = [x["command"] for x in sent if x.get("command")]
    return {"status": "sent" if cids else "no_helper", "command": cids[0] if cids else None, "commands": cids,
            "steps": steps + [{"t": f"Stop sent to {len(cids)} robot(s), no tap needed", "ok": True}],
            "reply": await new_reply("stop_all", lang, also_mac)}


async def send_device(dev, action: str, steps: list, lang: str, also_mac: bool, file: str | None = None,
                      place: str | None = None) -> dict:
    if hub.helper is None:
        hub.log.append("device.failed", actor="hub", content={"device": dev.id, "why": "no helper connected"})
        return {"status": "no_helper", "steps": steps + [{"t": "No helper is connected on the Mac", "ok": False}],
                "reply": await new_reply("no_helper", lang, False)}
    cid = uuid.uuid4().hex[:12]
    hub.commands[cid] = {"state": "sent", "detail": "Sent to the Mac", "device": dev.id, "kind": dev.kind,
                         "action": action, "file": file, "place": place, "proof": None, "lang": lang,
                         "also_mac": also_mac, "reply": None}
    msg = {"type": "device", "command_id": cid, "device_id": dev.id, "action": action}
    if place:
        msg["arg"] = place
    if file:  # printing: the helper downloads the file with a one-time token, as for opening
        ftoken = secrets.token_urlsafe(18)
        hub.file_tokens[ftoken] = file
        msg |= {"file_id": file, "filename": BY_ID[file].filename, "token": ftoken}
    hub.log.append("device.command", actor="hub", content={"command": cid, "do": say_action(action), "device": dev.id,
                                                           **({"file": file} if file else {})})
    await hub.helper.send_json(msg)
    return {"status": "sent", "command": cid, "steps": steps + [{"t": "Sent to the Mac", "ok": True}]}


def device_outcome(c: dict, msg: dict, confirmed: bool) -> tuple[str, dict]:
    """Which sentence the agent says after a device result."""
    kind, action, kw = c["kind"], c["action"], {"device": c["device"]}
    dev = devices.by_id(c["device"])
    if kind == "robot" and dev is not None and dev.sub == "sphero":
        if not msg.get("ok"):
            return ("robot_problem", kw | {"problem": msg["problem"]}) if msg.get("problem") else ("robot_failed", kw)
        return ("robot_stop" if action == "stop" else "lamp_colour" if action == "colour" else "sphero_did"), \
            kw | {"action": action, "place": c.get("place") or ""}
    if kind == "switchbot":
        if not msg.get("ok"):
            return "switch_failed", kw
        if not confirmed:
            return "bot_unsure", kw
        return ("bot_pressed" if action == "press" else action), kw
    if kind == "ble_lamp" and msg.get("ok") and confirmed and action in ("colour", "brighter", "dimmer"):
        return f"lamp_{action}", kw | {"place": c.get("place") or ""}
    if kind == "robot":
        kw["place"] = c.get("place") or msg.get("target") or ""
        if not msg.get("ok"):
            return ("robot_problem", kw | {"problem": msg["problem"]}) if msg.get("problem") else ("robot_failed", kw)
        if not confirmed:
            if action in ("goto", "dock") and msg.get("state") == "idle":
                return "robot_stopped_early", kw | {"place": kw["place"] or "dock"}
            return ("robot_on_way", kw) if msg.get("state") == "moving" else ("robot_unsure", kw)
        return f"robot_{action}", kw
    if not msg.get("ok"):
        if kind == "printer":
            problems = msg.get("problems") or []
            return ("printer_problem", kw | {"problem": ", ".join(problems)}) if problems else ("print_failed", kw)
        return ("tv_failed" if kind == "tv" else "switch_failed"), kw
    if kind == "tv" and action == "hdmi":
        return "hdmi", kw
    if not confirmed:
        return {"plug": "switch_unseen", "tv": "tv_unsure", "printer": "print_waiting", "ir": "switch_unseen",
                "ble_lamp": "switch_unseen"}[kind], kw
    if kind == "ir" and action not in ("on", "off"):
        return "ir_pressed", kw | {"action": action}
    if kind == "printer":
        return "printed", kw | {"file": c["file"]}
    if kind == "tv":
        if action.startswith("volume"):
            return action, kw | {"before": msg.get("before", ""), "after": msg.get("after", "")}
        if action == "mute":
            return ("muted" if msg.get("muted") else "unmuted"), kw
        if action.startswith("app:"):
            return "app", kw | {"app": msg.get("app", "")}
        if action == "pair":
            return "tv_paired", kw
    return action, kw


@app.get("/api/devices")
def devices_info(request: Request, x_session: str | None = Header(default=None)):
    who(request, x_session)
    pretend = devices.plug_kind() == "pretend"
    from .connectors.robots import plain
    out = []
    for d in devices.current():
        row = {"id": d.id, "name": d.name, "room": d.room, "kind": d.kind, "model": d.model,
               "on": hub.device_state.get(d.id), "pretend": (d.id == devices.LAMP.id and pretend) or d.id in devices.PRETENDS,
               "roles": list(d.roles)}
        if d.kind == "robot":
            st = hub.robot_state.get(d.id, {})
            row |= {"sub": d.sub, "places": list(d.place_names), "state": plain(st.get("state")) if st else None,
                    "battery": st.get("battery"), "place": st.get("place")}
        if d.kind == "ir":
            row["buttons"] = list(d.actions)
        out.append(row)
    return out


def mac_only(request: Request) -> None:
    if not is_local(request.client.host if request.client else None):
        raise HTTPException(403, "Only on the Mac itself")


@app.post("/api/scan")
async def scan_wifi(request: Request):
    """Listen for devices on the Wi-Fi (about 6 seconds). Controls nothing."""
    mac_only(request)
    found = await asyncio.to_thread(discover.scan, 6)
    for b in await asyncio.to_thread(ir_blaster.discover, 3):  # IR blasters (needs the broadlink library)
        found.append(b | {"key": discover.key_for("ir", b["mac"] or b["address"]), "uid": str(b.get("devtype") or "")})
    hub.found = {f["key"]: f for f in found}
    hub.log.append("network.scanned", actor="hub", content={"found": str(len(found)),
                                                            "kinds": ", ".join(sorted({f["kind"] for f in found}))})
    added = {d.id for d in devices.load_added()}
    return [{k: v for k, v in f.items() if k not in ("uid", "mac")} | {"added": f["key"] in added} for f in found]


@app.post("/api/devices/add")
async def add_device(request: Request):
    mac_only(request)
    body = await request.json()
    f = hub.found.get(str(body.get("key", "")))
    if not f:
        raise HTTPException(404, "Scan first, then add a device from the list")
    try:
        dev = devices.from_found(f, body.get("name", ""), body.get("room", ""), body.get("roles") or [],
                                 body.get("name_ar", ""), risky=bool(body.get("risky")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    devices.save_added([d for d in devices.load_added() if d.id != dev.id] + [dev])
    hub.log.append("device.added", actor="owner", content={"device": dev.id, "kind": dev.kind, "name": dev.name,
                                                           "room": dev.room, "roles": ", ".join(dev.roles)})
    out = {"status": "added", "device": dev.id}
    if dev.kind == "tv":  # the TV shows "Allow" on screen now; the page follows this command
        out["pairing"] = await send_device(dev, "pair", [{"t": f"Added “{dev.name}”", "ok": True},
                                                         {"t": "Look at the TV: accept “Allow” with the remote", "ok": None}],
                                           "en", False)
    return out


ROBOROCK_LOGIN = RUN_DIR / "roborock.json"
EMAIL = __import__("re").compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$", __import__("re").IGNORECASE)


def vacuum_rows(vacs: list[dict]) -> list[dict]:
    """Roborock vacuums as rows the page can add, like scan results."""
    rows = []
    for v in vacs:
        k = discover.key_for("robot", "roborock:" + v["duid"])
        rows.append({"key": k, "kind": "robot", "sub": "vacuum", "uid": v["duid"], "label": v["label"], "model": v["model"],
                     "address": "Roborock account", "places": [[name] for _, name in v["rooms"]],
                     "spots": [[name, seg] for seg, name in v["rooms"]], "connector": True})
    hub.found.update({r["key"]: r for r in rows})
    added = {d.id for d in devices.load_added()}
    return [{k: v for k, v in r.items() if k not in ("uid", "spots")} | {"added": r["key"] in added} for r in rows]


@app.post("/api/roborock/code")
async def roborock_code(request: Request):
    """Step 1: Roborock emails a code to the account's address."""
    mac_only(request)
    email = str((await request.json()).get("email", "")).strip()
    if not EMAIL.match(email):
        raise HTTPException(400, "Type the email you use in the Roborock app")
    try:
        await asyncio.to_thread(roborock_vac.request_code, email)
    except roborock_vac.VacuumError as e:
        raise HTTPException(502, str(e))
    hub.roborock_email = email
    return {"status": "code_sent"}


@app.post("/api/roborock/login")
async def roborock_login(request: Request):
    """Step 2: the emailed code logs in; the vacuums on the account are listed to add."""
    mac_only(request)
    code = str((await request.json()).get("code", "")).strip()
    email = getattr(hub, "roborock_email", None)
    if not email or not code.isdigit():
        raise HTTPException(400, "Ask for a code first, then type the digits from the email")
    try:
        await asyncio.to_thread(roborock_vac.login, email, code, ROBOROCK_LOGIN)
        vacs = await asyncio.to_thread(roborock_vac.list_vacuums, ROBOROCK_LOGIN)
    except roborock_vac.VacuumError as e:
        raise HTTPException(502, str(e))
    hub.log.append("robot.login", actor="owner", content={"brand": "Roborock", "vacuums": str(len(vacs))})
    return vacuum_rows(vacs)


@app.post("/api/roborock/list")
async def roborock_list(request: Request):
    mac_only(request)
    try:
        return vacuum_rows(await asyncio.to_thread(roborock_vac.list_vacuums, ROBOROCK_LOGIN))
    except roborock_vac.VacuumError as e:
        raise HTTPException(502, str(e))


def parse_spots(text: str) -> list[list]:
    """'Meeting room: 4, 2, 0' per line -> [[name, x, y, heading]]."""
    spots = []
    for line in str(text or "").splitlines():
        if not line.strip():
            continue
        name, _, nums = line.partition(":")
        try:
            vals = [float(v) for v in nums.replace(" ", "").split(",")]
        except ValueError:
            raise HTTPException(400, f"Spot “{line.strip()[:40]}”: write it as  Name: x, y, heading")
        if not devices.clean(name, 30) or len(vals) not in (2, 3):
            raise HTTPException(400, f"Spot “{line.strip()[:40]}”: write it as  Name: x, y, heading")
        spots.append([devices.clean(name, 30), vals[0], vals[1], vals[2] if len(vals) == 3 else 0.0])
    if not spots:
        raise HTTPException(400, "Add at least one spot, e.g.  Meeting room: 4, 2, 0")
    return spots[:20]


@app.post("/api/devices/add-ros")
async def add_ros(request: Request):
    """Add a ROS 2 robot by its rosbridge address and named spots (Mac only)."""
    mac_only(request)
    b = await request.json()
    address = str(b.get("address", "")).strip()
    if not __import__("re").fullmatch(r"[A-Za-z0-9.-]{1,100}", address):
        raise HTTPException(400, "Type the robot's IP address or host name")
    port = int(b.get("port") or 9090)
    if not 1 <= port <= 65535:
        raise HTTPException(400, "Port must be a number like 9090")
    spots = parse_spots(b.get("spots", ""))
    found = {"key": discover.key_for("robot", f"ros:{address}:{port}"), "kind": "robot", "sub": "ros",
             "label": "ROS robot", "model": "ROS 2", "address": address, "port": port,
             "places": [[s[0]] for s in spots], "spots": spots}
    try:
        dev = devices.from_found(found, b.get("name", "") or "ROS robot", b.get("room", ""), b.get("roles") or [])
    except ValueError as e:
        raise HTTPException(400, str(e))
    devices.save_added([d for d in devices.load_added() if d.id != dev.id] + [dev])
    hub.log.append("device.added", actor="owner", content={"device": dev.id, "kind": "robot (ROS)", "name": dev.name,
                                                           "room": dev.room, "roles": ", ".join(dev.roles)})
    return {"status": "added", "device": dev.id}


@app.post("/api/devices/add-ir")
async def add_ir(request: Request):
    """Add something with an infrared remote (e.g. a lamp), worked through a Wi-Fi IR blaster (Mac only).
    Its buttons are taught next, one by one (/learn)."""
    mac_only(request)
    b = await request.json()
    address = str(b.get("address", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,100}", address):
        raise HTTPException(400, "Type the IR blaster's IP address (the Broadlink app shows it)")
    mac = str(b.get("mac", "")).strip().lower()
    if mac and not re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
        raise HTTPException(400, "The blaster's MAC address looks like aa:bb:cc:dd:ee:ff (or leave it empty)")
    name = str(b.get("name", "")) or "lamp"
    found = {"key": discover.key_for("ir", f"{address}:{name.lower()}"), "kind": "ir", "label": "IR remote",
             "model": "via IR blaster", "address": address, "mac": mac or None,
             "uid": str(b.get("devtype") or "") or None}
    try:
        dev = devices.from_found(found, name, b.get("room", ""), b.get("roles") or [], b.get("name_ar", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    devices.save_added([d for d in devices.load_added() if d.id != dev.id] + [dev])
    hub.log.append("device.added", actor="owner", content={"device": dev.id, "kind": "ir", "name": dev.name,
                                                           "room": dev.room, "roles": ", ".join(dev.roles)})
    return {"status": "added", "device": dev.id, "buttons": list(devices.IR_BUTTONS)}


def blaster_for(dev):
    return ir_blaster.IRBlaster(dev.address, dev.mac, int(dev.uid) if (dev.uid or "").isdigit() else None)


@app.post("/api/devices/{device_id}/learn")
async def learn_button(device_id: str, request: Request):
    """Teach one button: the blaster listens for up to 20 seconds while you press it on the remote (Mac only)."""
    mac_only(request)
    button = str((await request.json()).get("button", ""))
    if button not in devices.IR_BUTTONS:
        raise HTTPException(400, f"Choose one of: {', '.join(devices.IR_BUTTONS)}")
    dev = next((d for d in devices.load_added() if d.id == device_id and d.kind == "ir"), None)
    if dev is None:
        raise HTTPException(404, "Not a device with a learned remote")
    try:
        code = await asyncio.to_thread(blaster_for(dev).learn)
        devices.teach(device_id, button, code)
    except (ir_blaster.IRError, ValueError) as e:
        raise HTTPException(400, str(e))
    hub.log.append("device.added", actor="owner", content={"device": dev.id, "kind": "ir", "name": dev.name,
                                                           "button": button})
    return {"status": "learned", "button": button,
            "buttons": [b[0] for b in devices.by_id(device_id).buttons] if devices.by_id(device_id) else [button]}


@app.post("/api/bt-scan")
async def bt_scan(request: Request):
    """Listen for Bluetooth devices near the Mac and near every relay (about 8 seconds). Controls nothing."""
    mac_only(request)
    if hub.helper is None:
        raise HTTPException(409, "The Mac helper isn't connected")
    rid = uuid.uuid4().hex[:12]
    fut = asyncio.get_running_loop().create_future()
    hub.finds[rid] = fut
    await hub.helper.send_json({"type": "bt_scan", "request_id": rid})
    try:
        got = await asyncio.wait_for(fut, 30)
    except asyncio.TimeoutError:
        raise HTTPException(504, "No answer from the Mac's Bluetooth")
    finally:
        hub.finds.pop(rid, None)
    items = [i for i in got["items"] if isinstance(i, dict) and str(i.get("key", "")).startswith("bt-")][:60]
    for i in items:
        if i.get("connector"):
            hub.found[i["key"]] = i
    hub.log.append("network.scanned", actor="hub", content={"bluetooth": str(len(items)),
                                                            "kinds": ", ".join(sorted({i["kind"] for i in items}))})
    added = {d.id for d in devices.load_added()}
    return {"items": [{k: v for k, v in i.items() if k not in ("uid",)} | {"added": i["key"] in added} for i in items],
            "problems": [str(p)[:200] for p in got["problems"]][:5]}


@app.get("/api/relays")
def relays_list(request: Request):
    mac_only(request)
    return bluetooth.public_relays()


@app.post("/api/relays")
async def relays_add(request: Request):
    mac_only(request)
    b = await request.json()
    try:
        row = bluetooth.add_relay(b.get("name", ""), b.get("host", ""), b.get("key", ""))
    except bluetooth.BluetoothError as e:
        raise HTTPException(400, str(e))
    hub.log.append("relay.added", actor="owner", content={"relay": row["id"], "name": row["name"]})
    return row


@app.delete("/api/relays/{relay_id}")
def relays_remove(relay_id: str, request: Request):
    mac_only(request)
    if not bluetooth.remove_relay(relay_id):
        raise HTTPException(404, "No such relay")
    hub.log.append("relay.removed", actor="owner", content={"relay": relay_id})
    return {"status": "removed"}


@app.get("/api/sites")
def sites_list(request: Request):
    mac_only(request)
    return sites.load()


@app.post("/api/sites")
async def sites_add(request: Request):
    mac_only(request)
    b = await request.json()
    try:
        row = sites.add(b.get("name", ""), b.get("url", ""), [w for w in str(b.get("words", "")).split(",")])
    except sites.SiteError as e:
        raise HTTPException(400, str(e))
    hub.log.append("site.saved", actor="owner", content={"site": row["name"]})
    return row


@app.delete("/api/sites/{site_id}")
def sites_remove(site_id: str, request: Request):
    mac_only(request)
    if not sites.remove(site_id):
        raise HTTPException(404, "Not a saved website")
    hub.log.append("site.removed", actor="owner", content={"site": site_id})
    return {"status": "removed"}


@app.get("/api/understanding")
def understanding(request: Request, x_session: str | None = Header(default=None)):
    who(request, x_session)
    return {"groq": understand.enabled()}


@app.get("/api/folder")
def folder_info(request: Request):
    mac_only(request)
    st = library.settings()
    lib = get_library()
    counts = None
    if lib:
        total, no_text = lib.db.execute("SELECT count(*), sum(has_text=0) FROM files").fetchone()
        counts = {"files": total, "no_text": no_text or 0}
    return {"folder": st["folder"] if st else None, "roles": st["roles"] if st else [], "counts": counts,
            "default": str(library.DEFAULT_FOLDER)}


@app.post("/api/folder")
async def folder_share(request: Request):
    """Share one folder for searching (the owner's choice, on the Mac), then read it."""
    mac_only(request)
    b = await request.json()
    try:
        folder = library.check_folder(b.get("folder", ""))
    except library.FolderError as e:
        raise HTTPException(400, str(e))
    roles = [r for r in devices.ROLES if r in set(b.get("roles") or [])]
    if not roles:
        raise HTTPException(400, "Tick at least one role who may open files from it")
    if hub.library:
        hub.library.close()
        hub.library = None
    library.share(folder, roles)
    hub.log.append("folder.shared", actor="owner", content={"folder": folder.name, "roles": ", ".join(roles)})
    return await folder_reindex(request)


@app.post("/api/folder/reindex")
async def folder_reindex(request: Request):
    mac_only(request)
    lib = get_library()
    if not lib:
        raise HTTPException(400, "Share a folder first")
    counts = await asyncio.to_thread(lib.index)
    hub.log.append("folder.indexed", actor="hub", content={k: str(v) for k, v in counts.items()})
    return {"folder": str(lib.folder), **counts}


@app.post("/api/folder/samples")
async def folder_samples(request: Request):
    """Copy the 3 made-up sample reports into the shared folder."""
    mac_only(request)
    lib = get_library()
    if not lib:
        raise HTTPException(400, "Share a folder first")
    import shutil
    src = ROOT / "samples" / "shared"
    if not src.exists() or not any(src.iterdir()):
        raise HTTPException(404, "Sample files missing: run scripts/make_sample_pdfs.py")
    for f in src.iterdir():
        if f.is_file() and not f.name.startswith("."):
            shutil.copy2(f, lib.folder / f.name)
    return await folder_reindex(request)


@app.delete("/api/folder")
def folder_unshare(request: Request):
    mac_only(request)
    if hub.library:
        hub.library.close()
        hub.library = None
    library.unshare()
    hub.log.append("folder.unshared", actor="owner", content={})
    return {"status": "unshared"}


async def reindex_now() -> None:
    lib = get_library()
    if lib:
        try:
            counts = await asyncio.to_thread(lib.index)
            if counts["changed"]:
                hub.log.append("folder.indexed", actor="hub", content={k: str(v) for k, v in counts.items()})
        except Exception:
            pass


async def keep_index_fresh() -> None:
    """The shared folder's search index follows the folder live: macOS tells us the moment a file is added,
    changed or deleted (mac_map.Watcher), and only then is the folder read again. Sharing a different folder
    moves the watch to it."""
    loop = asyncio.get_running_loop()
    watcher, watching = None, None
    try:
        while True:
            st = library.settings()
            folder = str(Path(st["folder"]).resolve()) if st else None
            if folder != watching:
                if watcher:
                    watcher.stop()
                watcher, watching = None, folder
                if folder:
                    watcher = mac_map.Watcher([folder], lambda: asyncio.run_coroutine_threadsafe(reindex_now(), loop),
                                              recursive=True).start()
            await asyncio.sleep(2)  # only checks which folder is shared; the files themselves are watched
    finally:
        if watcher:
            watcher.stop()


@app.delete("/api/devices/{device_id}")
def remove_device(device_id: str, request: Request):
    mac_only(request)
    left = [d for d in devices.load_added() if d.id != device_id]
    if len(left) == len(devices.load_added()):
        raise HTTPException(404, "Not an added device")
    devices.save_added(left)
    (devices.RUN_DIR / f"tv-{device_id}.token").unlink(missing_ok=True)
    (devices.RUN_DIR / f"ros-{device_id}.json").unlink(missing_ok=True)
    hub.device_state.pop(device_id, None)
    hub.log.append("device.removed", actor="owner", content={"device": device_id})
    return {"status": "removed"}


@app.get("/api/status/{cid}")
def status(cid: str, request: Request, x_session: str | None = Header(default=None)):
    who(request, x_session)
    c = hub.commands.get(cid)
    if not c:
        raise HTTPException(404, "Unknown command")
    return {"state": c["state"], "detail": c["detail"], "proof": c["proof"] is not None, "reply": c["reply"],
            "device": c.get("device"), "kind": c.get("kind")}


@app.get("/api/proof/{cid}")
def proof(cid: str, request: Request, s: str | None = None):
    # an <img> can't send headers, so the session comes as ?s=
    who(request, s)
    c = hub.commands.get(cid)
    if not c or not c["proof"]:
        raise HTTPException(404, "No proof yet")
    return Response(c["proof"], media_type="image/jpeg")


@app.post("/api/approve/{aid}")
async def approve(aid: str, request: Request, x_session: str | None = Header(default=None)):
    who(request, x_session)
    a = hub.approvals.get(aid)
    if not a:
        raise HTTPException(404, "Unknown approval")
    if a.get("cancelled") and "device" not in a:
        return {"status": "cancelled", "then": "cancelled", "note": "Cancelled before you approved",
                "steps": [{"t": "Cancelled before you approved", "ok": False}]}
    first = not a["done"]
    out = await approve_one(aid, a)
    if first and a.get("plan") and not a.get("cancelled"):
        task = asyncio.create_task(resume_plan(aid, out))
        hub.tasks.add(task)
        task.add_done_callback(hub.tasks.discard)
    return out


async def approve_one(aid: str, a: dict) -> dict:
    if a.get("site_add"):
        if a["done"]:
            return a["answer"] | {"repeat": True}
        a["done"] = True
        try:
            row = sites.add(a["name"], a["url"], [a["name"].lower().replace(" website", "")])
        except sites.SiteError as e:
            raise HTTPException(400, str(e))
        hub.log.append("approval.given", actor=a["by"], content={"approval": aid, "action": "save website", "site": row["name"]},
                       key=f"approval:{aid}")
        a["answer"] = await run_site(row["id"], a["target"], a["person"], [{"t": f"Saved “{row['name']}”", "ok": True}],
                                     a["lang"], a["also_mac"])
        return a["answer"] | {"then": a["answer"]["status"]}
    if "device" in a:
        if a.get("cancelled"):
            return {"status": "cancelled", "then": "cancelled", "note": "Cancelled: Stop was said before you approved",
                    "steps": [{"t": "Cancelled: Stop was said before you approved", "ok": False}]}
        if a["done"]:
            return a["answer"] | {"repeat": True}
        a["done"] = True
        hub.log.append("approval.given", actor=a["by"], content={"approval": aid, "device": a["device"],
                                                                  "action": a["action"]}, key=f"approval:{aid}")
        dev = devices.by_id(a["device"])
        if dev is None:
            raise HTTPException(410, "That device was removed")
        a["answer"] = await send_device(dev, a["action"], [{"t": "Approved by you", "ok": True}],
                                        a["lang"], a["also_mac"], file=a.get("file"), place=a.get("place"))
        return a["answer"] | {"status": "approved", "then": a["answer"]["status"]}
    if not a["done"]:
        a["done"] = True
        hub.log.append("approval.given", actor=a["by"], content={"approval": aid, "file": a["file"], "to": a["to"],
                                                                  "note": "demo: would send; nothing was emailed"},
                       key=f"approval:{aid}")
        a["reply"] = await new_reply("approved", a.get("lang", "en"), a.get("also_mac", False))
    return {"status": "approved", "reply": a.get("reply"),
            "note": f"Approved. Demo only: logged “would send {BY_ID[a['file']].title} to {a['to']}”. Nothing was emailed."}


@app.get("/api/reply/{rid}.m4a")
async def reply_file(rid: str, request: Request, s: str | None = None):
    # an <audio> element can't send headers, so the session comes as ?s=
    who(request, s)
    if rid not in hub.replies:
        raise HTTPException(404, "Unknown reply")
    r = await reply_audio(rid)
    hub.log.append("reply.spoken", actor="hub", content={"reply": rid, "where": "device", "voice": r["note"]},
                   key=f"spoken-device:{rid}")
    return Response(r["audio"], media_type="audio/mp4", headers={"X-Voice": r["note"].encode("ascii", "ignore").decode()})


# ---------------- the owner's voice sample (this Mac only, consent required) ----------------

@app.get("/api/voice")
def voice_info(request: Request, x_session: str | None = Header(default=None)):
    who(request, x_session)
    return {"sample": voice.SAMPLE.exists(), "magpie": voice.magpie_ready("en") or "on"}


@app.post("/api/voice-sample")
async def voice_sample(request: Request, consent: str = ""):
    if not is_local(request.client.host if request.client else None):
        raise HTTPException(403, "Record your voice on the Mac itself")
    if consent != "my-own-voice":
        raise HTTPException(400, "Tick “This is my own voice” first")
    kind = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if kind not in AUDIO_TYPES:
        raise HTTPException(415, "Send the recording as audio")
    audio = await request.body()
    if not 2000 < len(audio) < speech.MAX_BYTES:
        raise HTTPException(400, "The recording is empty or too long")
    RUN_DIR.mkdir(exist_ok=True)
    src = RUN_DIR / f"voice-upload{AUDIO_TYPES[kind]}"
    src.write_bytes(audio)
    # NVIDIA asks for 3-5 s, 16-bit mono WAV at 22.05 kHz
    r = await asyncio.to_thread(subprocess.run, ["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-t", "5",
                                                 "-ac", "1", "-ar", "22050", "-sample_fmt", "s16", str(voice.SAMPLE)],
                                capture_output=True)
    src.unlink(missing_ok=True)
    if r.returncode != 0:
        raise HTTPException(400, "Couldn't read that recording")
    voice.SAMPLE.chmod(0o600)
    hub.log.append("voice.sample_saved", actor=PEOPLE["layla"]["name"], content={"consent": "own voice, for replies"})
    return {"saved": True}


@app.delete("/api/voice-sample")
def voice_sample_delete(request: Request):
    if not is_local(request.client.host if request.client else None):
        raise HTTPException(403, "Only on the Mac itself")
    if voice.SAMPLE.exists():
        voice.SAMPLE.unlink()
        hub.log.append("voice.sample_deleted", actor=PEOPLE["layla"]["name"])
    return {"deleted": True}


AUDIO_TYPES = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".mp4", "audio/mpeg": ".mp3",
               "audio/wav": ".wav", "audio/x-m4a": ".m4a", "audio/aac": ".aac"}


@app.post("/api/transcribe")
async def transcribe(request: Request, x_session: str | None = Header(default=None)):
    """Voice clip from the page's mic -> text, on this Mac (Whisper). The page then runs the text as a command."""
    who(request, x_session)
    kind = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if kind not in AUDIO_TYPES:
        raise HTTPException(415, "Send the recording as audio")
    audio = await request.body()
    try:
        return await asyncio.to_thread(speech.transcribe, audio, AUDIO_TYPES[kind])
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/events")
def events(request: Request, x_session: str | None = Header(default=None)):
    who(request, x_session)
    return hub.log.latest(25)


# ---------------- the helper's side: this Mac only ----------------

@app.get("/helper/file/{file_id}")
def helper_file(file_id: str, request: Request, t: str = ""):
    if not is_local(request.client.host if request.client else None):
        raise HTTPException(403, "Only the helper on this Mac can download files")
    if hub.file_tokens.pop(t, None) != file_id:  # one use only, and only for that file
        raise HTTPException(403, "Bad or used token")
    if file_id.startswith("lib-") and file_id[4:].isdigit():
        lib = get_library()
        path = lib.path_of(int(file_id[4:])) if lib else None  # checked again: still inside the shared folder
        if path is None:
            raise HTTPException(404, "That file isn't in the shared folder any more")
        return FileResponse(path, filename=file_id + path.suffix.lower())
    rec = BY_ID[file_id]
    if not rec.path.exists():
        raise HTTPException(404, "File missing: run scripts/make_sample_pdfs.py")
    return FileResponse(rec.path, media_type="application/pdf", filename=rec.filename)


@app.get("/helper/reply/{rid}")
async def helper_reply(rid: str, request: Request, t: str = ""):
    if not is_local(request.client.host if request.client else None):
        raise HTTPException(403, "Only the helper on this Mac can fetch replies")
    if hub.reply_tokens.pop(t, None) != rid:  # one use only, and only for that reply
        raise HTTPException(403, "Bad or used token")
    r = await reply_audio(rid)
    return Response(r["audio"], media_type="audio/mp4")


@app.websocket("/helper/ws")
async def helper_ws(ws: WebSocket):
    if not is_local(ws.client.host if ws.client else None) or ws.query_params.get("token") != hub.helper_token:
        await ws.close(code=4403)
        return
    await ws.accept()
    hub.helper = ws
    hub.log.append("helper.connected", actor="helper")
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "map":  # the live app map: the full list on connect, then each change at once
                clean = lambda xs: [str(x)[:80] for x in (xs or []) if isinstance(x, str) and x.strip()][:2000]
                if "apps" in msg:
                    hub.mac_apps = set(clean(msg["apps"]))
                for name in clean(msg.get("added")):
                    hub.mac_apps.add(name)
                    hub.log.append("map.added", actor="helper", content={"app": name})
                for name in clean(msg.get("removed")):
                    hub.mac_apps.discard(name)
                    hub.log.append("map.removed", actor="helper", content={"app": name})
                continue
            if msg.get("type") == "bt_found":
                fut = hub.finds.pop(str(msg.get("request_id")), None)
                if fut and not fut.done():
                    fut.set_result({"items": msg.get("items") or [], "problems": msg.get("problems") or []})
                continue
            if msg.get("type") == "found":
                fut = hub.finds.pop(str(msg.get("request_id")), None)
                if fut and not fut.done():
                    fut.set_result(msg.get("items") or [])
                continue
            if msg.get("type") == "spoken" and msg.get("reply_id") in hub.replies:
                r = hub.replies[msg["reply_id"]]
                hub.log.append("reply.spoken", actor="helper",
                               content={"reply": msg["reply_id"], "where": "Mac speakers" if msg.get("ok") else "Mac (failed)",
                                        "voice": r["note"]}, key=f"spoken-mac:{msg['reply_id']}")
                continue
            if msg.get("type") != "result" or msg.get("command_id") not in hub.commands:
                continue
            c = hub.commands[msg["command_id"]]
            if msg.get("proof_b64"):
                c["proof"] = base64.b64decode(msg["proof_b64"])
            confirmed = bool(msg.get("ok")) and bool(msg.get("confirmed"))
            state = "confirmed" if confirmed else ("unconfirmed" if msg.get("ok") else "failed")
            if "device" in c and isinstance(msg.get("state"), bool):
                hub.device_state[c["device"]] = msg["state"]
            if c.get("kind") == "robot" and isinstance(msg.get("state"), str):
                hub.robot_state[c["device"]] = {"state": msg["state"], "battery": msg.get("battery"),
                                                "place": msg.get("place") or msg.get("target")}
            if c.get("reply") is None:  # attach the reply BEFORE the state changes: the page stops polling then
                if "mac" in c:
                    after = msg.get("after")
                    outcome = ("mac_muted" if c["mac"] == "mute" else "mac_volume_is" if c["mac"] == "get"
                               else "mac_volume") if confirmed else ("mac_volume_unsure" if msg.get("ok") else "app_failed")
                    if confirmed and c["mac"] == "get" and msg.get("muted"):
                        outcome = "mac_volume_is_muted"
                    c["reply"] = await new_reply(outcome, c.get("lang", "en"), c.get("also_mac", False),
                                                 after="" if after is None else after, app="the Mac")
                elif "app" in c:
                    outcome = ("app_draft_mac" if c["draft"] else "app_mac") if confirmed else \
                        ("app_unconfirmed" if msg.get("ok") else "app_failed")
                    if confirmed and c["draft"] and c["app"] == "whatsapp":
                        outcome = "whatsapp_draft_mac"
                    c["reply"] = await new_reply(outcome, c.get("lang", "en"), c.get("also_mac", False), app=c["title"])
                elif "device" in c:
                    outcome, kw = device_outcome(c, msg, confirmed)
                    c["reply"] = await new_reply(outcome, c.get("lang", "en"), c.get("also_mac", False), **kw)
                else:
                    c["reply"] = await new_reply(state, c.get("lang", "en"), c.get("also_mac", False), file=c["file"],
                                                 title=c.get("title", ""))
            c["detail"] = str(msg.get("detail", ""))[:200]
            c["state"] = state
            what = {"device": c["device"], "action": c["action"]} if "device" in c else \
                {"app": c["app"]} if "app" in c else {"mac": c["mac"]} if "mac" in c else {"file": c["file"]}
            hub.log.append("device.confirmed" if confirmed else "device.failed", actor="helper",
                           content={"command": msg["command_id"], **what, "detail": c["detail"]},
                           key=f"result:{msg['command_id']}")
    except WebSocketDisconnect:
        pass
    finally:
        if hub.helper is ws:
            hub.helper = None
            hub.mac_apps = set()
            hub.log.append("helper.disconnected", actor="helper")


def lan_ip() -> str:
    """This Mac's address on the Wi-Fi. (A UDP 'connect' sends no packets; it only picks the route.)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def make_cert(ip: str) -> tuple[Path, Path]:
    """A self-signed certificate for this Mac's Wi-Fi address, so phones can use https (and so the mic).
    Made again whenever the address changes. Kept in run/ (never committed)."""
    cert, key, stamp = RUN_DIR / "cert.pem", RUN_DIR / "key.pem", RUN_DIR / "cert-ip"
    if not (cert.exists() and key.exists() and stamp.exists() and stamp.read_text() == ip):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30",
                        "-subj", "/CN=Diwan helper demo",
                        "-addext", f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost",
                        "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
        key.chmod(0o600)
        stamp.write_text(ip)
    return cert, key


async def serve() -> None:
    import uvicorn
    ip = lan_ip()
    cert, key = make_cert(ip)
    local = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    wifi = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=SECURE_PORT, log_level="warning",
                                         ssl_certfile=str(cert), ssl_keyfile=str(key)))
    print("\n  Site Witness hub (helper demo)")
    print(f"  On this Mac:        http://localhost:{PORT}")
    print(f"  On your phone:      https://{ip}:{SECURE_PORT}   (same Wi-Fi)")
    print("                      First time: Chrome says “not private” → Advanced → Proceed. That’s this Mac’s own certificate.")
    print(f"  Pairing code:       {hub.pair_code}")
    if os.environ.get("SW_PAIR_CODE"):
        print("  Note: a fixed pairing code (SW_PAIR_CODE) is for testing only. Leave it unset for a new code each run.")
    print("  Stop with Ctrl+C\n", flush=True)
    await asyncio.gather(local.serve(), wifi.serve(), keep_index_fresh())


def main():
    RUN_DIR.mkdir(exist_ok=True)
    tok = RUN_DIR / "helper-token"
    tok.write_text(hub.helper_token)
    tok.chmod(0o600)
    speech.warm_up()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
