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
import os
import subprocess
import secrets
import socket
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response

from . import devices, discover, phone_apps, speech, voice
from .connectors import roborock_vac
from .commands import parse
from .devices import may_use
from .replies import lang_of, reply
from .events import EventLog
from .records import BY_ID, PEOPLE, ROOT, allowed

RUN_DIR = ROOT / "run"
WEB = ROOT / "web"
PORT = int(os.environ.get("SW_PORT", "8040"))              # http, this Mac only (page + helper)
SECURE_PORT = int(os.environ.get("SW_SECURE_PORT", "8443"))  # https, for phones on the Wi-Fi (mic needs https)
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


class Hub:
    def __init__(self, db_path: str = ":memory:"):
        self.log = EventLog(db_path)
        self.pair_code = os.environ.get("SW_PAIR_CODE") or f"{secrets.randbelow(10**6):06d}"
        self.helper_token = secrets.token_urlsafe(24)
        self.sessions: set[str] = set()
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
    body = await request.json()
    if str(body.get("code", "")).strip() != hub.pair_code:
        raise HTTPException(403, "That code is not right. It is shown in the terminal on the Mac.")
    token = secrets.token_urlsafe(18)
    hub.sessions.add(token)
    hub.log.append("pairing.joined", actor="device", content={"from": request.client.host if request.client else "?"})
    return {"session": token}


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
    answer = await run_command(said, person, device, key, choose, lang, bool(body.get("also_mac")))
    if key:
        hub.results[key] = answer
    return answer


# ---------------- spoken replies ----------------

async def new_reply(outcome: str, lang: str, also_mac: bool, **kw) -> dict:
    """Make the sentence the agent says back. The audio is made when first asked for (and cached).
    With also_mac, the helper plays it through the Mac's speakers too."""
    rid = uuid.uuid4().hex[:10]
    hub.replies[rid] = {"text": reply(outcome, lang, **kw), "lang": lang, "audio": None, "engine": None, "note": None}
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


async def run_command(said: str, person: str, device: str, key: str | None, choose: str | None,
                      lang: str = "en", also_mac: bool = False) -> dict:
    name = PEOPLE[person]["name"]
    hub.log.append("command.heard", actor=name, content={"said": said, "device": device},
                   key=f"heard:{key}" if key else None)
    intent = parse(said)
    steps = [{"t": f"Heard “{said}”", "ok": True}]
    if intent.action == "phone_app":
        return await run_phone_app(intent, name, steps, lang, also_mac)
    if intent.kind:
        dev = devices.by_id(choose[4:]) if choose and choose.startswith("dev:") else intent.device
        return await run_device(intent, dev, person, steps, lang, also_mac, choose)
    matches = [BY_ID[choose]] if choose in BY_ID else intent.matches
    if not matches:
        hub.log.append("file.not_found", actor="hub", content={"said": said})
        return {"status": "not_found", "steps": steps + [{"t": "No file in Records matches that", "ok": False}],
                "reply": await new_reply("not_found", lang, also_mac)}
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


async def run_phone_app(intent, name: str, steps: list, lang: str, also_mac: bool) -> dict:
    """Open an app on the phone you spoke on. The phone opens it (after a tap); nothing is sent for you."""
    title = phone_apps.APPS[intent.app][0]
    url = phone_apps.link(intent.app, intent.message)
    hub.log.append("phone.app_opened", actor=name, content={"app": intent.app, "with_text": "yes" if intent.message else "no"})
    steps = steps + [{"t": f"Open {title} on this phone" + (" with your message typed (you press send)" if intent.message else ""),
                      "ok": True}]
    rep = await new_reply("phone_message" if intent.message else "phone_app", lang, also_mac, app=title)
    return {"status": "open_on_phone", "app": title, "link": url, "steps": steps, "reply": rep}


def say_action(action: str) -> str:
    return {"start": "start cleaning", "clean": "clean", "pause": "pause", "dock": "go home to charge", "goto": "go to",
            "stop": "stop", "volume_up": "volume up", "volume_down": "volume down", "app:youtube": "open YouTube",
            "app:netflix": "open Netflix", "hdmi": "change input", "print": "print"}.get(action, f"switch {action}")


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
    if kind == "robot":
        kw["place"] = c.get("place") or msg.get("target") or ""
        if not msg.get("ok"):
            return ("robot_problem", kw | {"problem": msg["problem"]}) if msg.get("problem") else ("robot_failed", kw)
        if not confirmed:
            if action == "goto" and msg.get("state") == "idle":
                return "robot_stopped_early", kw
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
        return {"plug": "switch_unseen", "tv": "tv_unsure", "printer": "print_waiting"}[kind], kw
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
                                 body.get("name_ar", ""))
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
                if "device" in c:
                    outcome, kw = device_outcome(c, msg, confirmed)
                    c["reply"] = await new_reply(outcome, c.get("lang", "en"), c.get("also_mac", False), **kw)
                else:
                    c["reply"] = await new_reply(state, c.get("lang", "en"), c.get("also_mac", False), file=c["file"])
            c["detail"] = str(msg.get("detail", ""))[:200]
            c["state"] = state
            what = {"device": c["device"], "action": c["action"]} if "device" in c else {"file": c["file"]}
            hub.log.append("device.confirmed" if confirmed else "device.failed", actor="helper",
                           content={"command": msg["command_id"], **what, "detail": c["detail"]},
                           key=f"result:{msg['command_id']}")
    except WebSocketDisconnect:
        pass
    finally:
        if hub.helper is ws:
            hub.helper = None
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
    print("  Stop with Ctrl+C\n", flush=True)
    await asyncio.gather(local.serve(), wifi.serve())


def main():
    RUN_DIR.mkdir(exist_ok=True)
    tok = RUN_DIR / "helper-token"
    tok.write_text(hub.helper_token)
    tok.chmod(0o600)
    speech.warm_up()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
