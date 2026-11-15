"""Diwan Helper: the small app on the computer that does what the hub asks, then proves it.

It connects *out* to the hub on this Mac. It does exactly one thing: open a file from Records.
- It only accepts a file ID that is in Records, with a one-time token it has not used before.
- It downloads the file from the hub (never opens a path it is sent), opens it in Preview,
  checks Preview really has it open, takes a screenshot as proof, and sends the result back.
- It never runs any other command.

macOS asks once for Screen Recording (the screenshot) and once to let Terminal talk to Preview
(the "is it open?" check). If either is refused, the result says "couldn't confirm" rather than
pretending it worked.

Run: python helper/diwan_helper.py   (./run-demo starts it for you)
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sitewitness.records import BY_ID  # noqa: E402

RUN_DIR = ROOT / "run"
OPENED = RUN_DIR / "opened"
PORT = int(os.environ.get("SW_PORT", "8040"))
HUB = f"127.0.0.1:{PORT}"
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.pdf$")


def run(cmd: list[str], timeout: float = 10) -> subprocess.CompletedProcess:
    """Run one macOS tool. A tool that hangs (for example behind a permission pop-up) counts as failed;
    it never stops the helper."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {timeout:.0f} s")


def download(file_id: str, token: str) -> bytes:
    with urllib.request.urlopen(f"http://{HUB}/helper/file/{file_id}?t={token}", timeout=10) as r:
        return r.read()


class Helper:
    def __init__(self, runner=run, fetch=download, opened_dir: Path = OPENED, wait: float = 6.0):
        self.run, self.fetch, self.opened_dir, self.wait = runner, fetch, opened_dir, wait
        self.used_tokens: set[str] = set()

    def check(self, msg: dict) -> str | None:
        """Why this message must be refused, or None if it is fine."""
        if msg.get("type") != "open_file":
            return "I only open files"
        if msg.get("file_id") not in BY_ID:
            return "Not a file in Records"
        if BY_ID[msg["file_id"]].filename != msg.get("filename") or not SAFE_NAME.match(msg.get("filename", "")):
            return "File name does not match Records"
        if not msg.get("token") or msg["token"] in self.used_tokens:
            return "Token missing or already used"
        if not re.fullmatch(r"[0-9a-f]{12}", str(msg.get("command_id", ""))):
            return "Bad command id"
        return None

    def open_file(self, msg: dict) -> dict:
        why = self.check(msg)
        result = {"type": "result", "command_id": msg.get("command_id"), "ok": False}
        if why:
            return result | {"detail": f"Refused: {why}"}
        self.used_tokens.add(msg["token"])
        try:
            data = self.fetch(msg["file_id"], msg["token"])
        except Exception as e:  # the hub refused, or is not there
            return result | {"detail": f"Could not get the file: {e}"}
        self.opened_dir.mkdir(parents=True, exist_ok=True)
        path = self.opened_dir / msg["filename"]
        path.write_bytes(data)
        if self.run(["open", "-a", "Preview", str(path)]).returncode != 0:
            return result | {"detail": "Preview would not open the file"}
        seen = self.is_open(path.name)
        proof = self.screenshot()
        if seen is None:
            return result | {"ok": True, "detail": "Opened in Preview, but I couldn't confirm it "
                             "(allow Terminal to control Preview)", "proof_b64": proof, "confirmed": False}
        if not seen:
            return result | {"detail": "Preview did not show the file", "proof_b64": proof}
        return result | {"ok": True, "detail": "Opened in Preview and confirmed", "proof_b64": proof, "confirmed": True}

    def is_open(self, name: str) -> bool | None:
        """True if Preview lists the document, False if not, None if macOS won't let us ask."""
        deadline = time.monotonic() + self.wait
        while True:
            r = self.run(["osascript", "-e", 'tell application "Preview" to get name of every document'])
            if r.returncode != 0:
                return None
            if name in r.stdout:
                return True
            if time.monotonic() > deadline:
                return False
            time.sleep(0.4)

    def screenshot(self) -> str | None:
        shot = RUN_DIR / "proof.jpg"
        shot.unlink(missing_ok=True)
        if self.run(["screencapture", "-x", "-t", "jpg", str(shot)]).returncode != 0 or not shot.exists():
            return None
        self.run(["sips", "-Z", "1100", str(shot)])
        return base64.b64encode(shot.read_bytes()).decode()


async def main():
    import websockets
    helper = Helper()
    print("  Diwan Helper: connecting to the hub on this Mac…", flush=True)
    while True:
        try:
            token = (RUN_DIR / "helper-token").read_text().strip()  # read each time: a restarted hub has a new one
            async with websockets.connect(f"ws://{HUB}/helper/ws?token={token}") as ws:
                print("  Diwan Helper: connected. Waiting for commands.", flush=True)
                async for raw in ws:
                    msg = json.loads(raw)
                    print(f"  Diwan Helper: asked to open {msg.get('file_id')}", flush=True)
                    try:
                        result = await asyncio.to_thread(helper.open_file, msg)
                    except Exception as e:  # never leave the hub waiting
                        result = {"type": "result", "command_id": msg.get("command_id"), "ok": False,
                                  "detail": f"Helper error: {type(e).__name__}"}
                    print(f"  Diwan Helper: {result['detail']}", flush=True)
                    await ws.send(json.dumps(result))
        except (OSError, Exception) as e:  # hub not up yet, or it restarted
            print(f"  Diwan Helper: hub not reachable ({type(e).__name__}); retrying in 2 s", flush=True)
            await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
