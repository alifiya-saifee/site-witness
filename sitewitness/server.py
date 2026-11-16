"""The hub: the control page, pairing, commands, approvals, and the line to the helper.

Run:  python -m sitewitness.server     (or ./run-demo, which also starts the helper)

Safety rules this file keeps:
- A phone or browser on the Wi-Fi must join with the 6-digit pairing code shown on the Mac.
  A browser on the Mac itself (localhost) is trusted without the code.
- Only a helper on this Mac, holding the helper token, can connect, and only it can download files.
- Each file download needs a one-time token tied to one command and one file.
- "Send" never sends: it creates an approval, and even an approved send is only logged in this demo.
- A repeated tap (same key) returns the first result; the file is not opened twice.
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

from . import speech
from .commands import parse
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
    answer = await run_command(said, person, device, key, choose)
    if key:
        hub.results[key] = answer
    return answer


async def run_command(said: str, person: str, device: str, key: str | None, choose: str | None) -> dict:
    name = PEOPLE[person]["name"]
    hub.log.append("command.heard", actor=name, content={"said": said, "device": device},
                   key=f"heard:{key}" if key else None)
    intent = parse(said)
    steps = [{"t": f"Heard “{said}”", "ok": True}]
    matches = [BY_ID[choose]] if choose in BY_ID else intent.matches
    if not matches:
        hub.log.append("file.not_found", actor="hub", content={"said": said})
        return {"status": "not_found", "steps": steps + [{"t": "No file in Records matches that", "ok": False}]}
    if len(matches) > 1:
        hub.log.append("file.ambiguous", actor="hub", content={"options": [r.id for r in matches]})
        return {"status": "choose", "steps": steps + [{"t": f"{len(matches)} files match. Which one?", "ok": None}],
                "options": [{"id": r.id, "title": r.title} for r in matches]}
    rec = matches[0]
    hub.log.append("file.matched", actor="hub", content={"file": rec.id, "title": rec.title})
    steps.append({"t": f"Found “{rec.title}”", "ok": True})
    if not allowed(person, rec):
        hub.log.append("access.refused", actor="hub", content={"file": rec.id, "person": person})
        return {"status": "refused", "steps": steps + [{"t": f"{name} is not allowed to open this file", "ok": False}]}
    steps.append({"t": f"Allowed for {name} ({PEOPLE[person]['role']})", "ok": True})

    if intent.action == "send":
        aid = uuid.uuid4().hex[:10]
        to = intent.recipient or "someone"
        hub.approvals[aid] = {"file": rec.id, "to": to, "by": name, "done": False}
        hub.log.append("approval.requested", actor="hub", content={"approval": aid, "action": "send", "file": rec.id, "to": to})
        return {"status": "needs_approval", "approval": aid, "question": f"Send “{rec.title}” to {to}?",
                "steps": steps + [{"t": "Sending a file needs your tap", "ok": None}]}

    if hub.helper is None:
        hub.log.append("device.failed", actor="hub", content={"file": rec.id, "why": "no helper connected"})
        return {"status": "no_helper", "steps": steps + [{"t": "No helper is connected on the Mac", "ok": False}]}
    cid, ftoken = uuid.uuid4().hex[:12], secrets.token_urlsafe(18)
    hub.file_tokens[ftoken] = rec.id
    hub.commands[cid] = {"state": "sent", "detail": "Sent to the Mac", "file": rec.id, "proof": None}
    hub.log.append("device.command", actor="hub", content={"command": cid, "do": "open_file", "file": rec.id})
    await hub.helper.send_json({"type": "open_file", "command_id": cid, "file_id": rec.id,
                                "filename": rec.filename, "token": ftoken})
    return {"status": "sent", "command": cid, "steps": steps + [{"t": "Sent to the Mac", "ok": True}]}


@app.get("/api/status/{cid}")
def status(cid: str, request: Request, x_session: str | None = Header(default=None)):
    who(request, x_session)
    c = hub.commands.get(cid)
    if not c:
        raise HTTPException(404, "Unknown command")
    return {"state": c["state"], "detail": c["detail"], "proof": c["proof"] is not None}


@app.get("/api/proof/{cid}")
def proof(cid: str, request: Request, s: str | None = None):
    # an <img> can't send headers, so the session comes as ?s=
    who(request, s)
    c = hub.commands.get(cid)
    if not c or not c["proof"]:
        raise HTTPException(404, "No proof yet")
    return Response(c["proof"], media_type="image/jpeg")


@app.post("/api/approve/{aid}")
def approve(aid: str, request: Request, x_session: str | None = Header(default=None)):
    who(request, x_session)
    a = hub.approvals.get(aid)
    if not a:
        raise HTTPException(404, "Unknown approval")
    if not a["done"]:
        a["done"] = True
        hub.log.append("approval.given", actor=a["by"], content={"approval": aid, "file": a["file"], "to": a["to"],
                                                                  "note": "demo: would send; nothing was emailed"},
                       key=f"approval:{aid}")
    return {"status": "approved", "note": f"Approved. Demo only: logged “would send {BY_ID[a['file']].title} to {a['to']}”. Nothing was emailed."}


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
            if msg.get("type") != "result" or msg.get("command_id") not in hub.commands:
                continue
            c = hub.commands[msg["command_id"]]
            if msg.get("proof_b64"):
                c["proof"] = base64.b64decode(msg["proof_b64"])
            confirmed = bool(msg.get("ok")) and bool(msg.get("confirmed"))
            c["state"] = "confirmed" if confirmed else ("unconfirmed" if msg.get("ok") else "failed")
            c["detail"] = str(msg.get("detail", ""))[:200]
            hub.log.append("device.confirmed" if confirmed else "device.failed", actor="helper",
                           content={"command": msg["command_id"], "file": c["file"], "detail": c["detail"]},
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
