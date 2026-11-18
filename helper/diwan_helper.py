"""Diwan Helper: the small app on the computer that does what the hub asks, then proves it.

It connects *out* to the hub on this Mac. It does these things, nothing else:
open a file (Records, the shared folder, or a file it just found for the Owner with Spotlight, by a one-time id),
open an app (the approved list in sitewitness/apps.py, or any app on its own live map of installed apps),
change or read the Mac's volume, open a saved website, run one allowed action on a device someone added
(plug, Samsung TV, printer, robot, a learned infrared remote), and play spoken replies.
It keeps the live app map (sitewitness/mac_map.py) and tells the hub the moment an app is installed or deleted.
- It only accepts a file ID that is in Records, with a one-time token it has not used before.
- It downloads the file from the hub (never opens a path it is sent), opens it in Preview,
  checks Preview really has it open, takes a screenshot as proof, and sends the result back.
- It never runs any other command.

macOS asks once for Screen Recording (the screenshot) and once to let Terminal talk to Preview
(the "is it open?" check). If either is refused, the result says "couldn't confirm" rather than
pretending it worked.

Switching a device: it takes a "before" photo with the Mac camera, switches the plug, reads the plug's
state back, takes an "after" photo, and checks the picture got brighter (on) or darker (off). If the camera
is blocked or sees no change, it says so ("couldn't see it") instead of claiming it worked.
macOS asks once for Camera access.

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
from sitewitness import apps, bluetooth, devices, mac_map, sites  # noqa: E402
from sitewitness.connectors import ble_lamp, sphero, switchbot  # noqa: E402
from sitewitness.connectors.ipp_printer import Printer, PrinterError  # noqa: E402
from sitewitness.connectors.ir_blaster import IRBlaster, IRError  # noqa: E402
from sitewitness.connectors.plug import PlugError, TapoPlug  # noqa: E402
from sitewitness.connectors.samsung_tv import SamsungTV  # noqa: E402
from sitewitness.connectors.robots import PretendRobot  # noqa: E402
from sitewitness.connectors.roborock_vac import RoborockVacuum  # noqa: E402
from sitewitness.connectors.ros_robot import RosRobot  # noqa: E402
from sitewitness.records import BY_ID  # noqa: E402

RUN_DIR = ROOT / "run"
OPENED = RUN_DIR / "opened"
PORT = int((os.environ.get("SW_PORT") or "8040"))
HUB = f"127.0.0.1:{PORT}"
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.pdf$")
SHARED_NAME = re.compile(r"^(lib-\d{1,9})\.(pdf|docx|txt|md)$")  # a shared-folder file: id + type, never a path
CAMERA = (os.environ.get("SW_CAMERA") or "0")   # 0 = the Mac's own camera (ffmpeg -list_devices shows others)
BRIGHTER = 8.0   # points out of 255 the picture must change by
BRIGHT_SHARE = 1.0  # or: % of near-white pixels must change by this much (the camera's auto-exposure hides some of it)


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


def download_reply(reply_id: str, token: str) -> bytes:
    with urllib.request.urlopen(f"http://{HUB}/helper/reply/{reply_id}?t={token}", timeout=30) as r:
        return r.read()


def brightness(jpg: bytes) -> tuple[float, float]:
    """(average brightness 0-255, % of near-white pixels) of a photo."""
    from io import BytesIO
    from PIL import Image, ImageStat
    im = Image.open(BytesIO(jpg)).convert("L")
    im.thumbnail((320, 320))
    hist = im.histogram()
    return ImageStat.Stat(im).mean[0], 100 * sum(hist[230:]) / max(1, sum(hist))


def side_by_side(before: bytes, after: bytes) -> bytes:
    """One proof picture: before | after."""
    from io import BytesIO
    from PIL import Image, ImageDraw
    a, b = (Image.open(BytesIO(x)).convert("RGB") for x in (before, after))
    for im in (a, b):
        im.thumbnail((640, 640))
    out = Image.new("RGB", (a.width + b.width + 10, max(a.height, b.height)), (10, 13, 19))
    out.paste(a, (0, 0)); out.paste(b, (a.width + 10, 0))
    d = ImageDraw.Draw(out)
    for x, label in ((8, "before"), (a.width + 18, "after")):
        d.rectangle([x - 4, 6, x + 52, 24], fill=(10, 13, 19)); d.text((x, 9), label, fill=(232, 199, 122))
    buf = BytesIO(); out.save(buf, "JPEG", quality=82)
    return buf.getvalue()


class Helper:
    def __init__(self, runner=run, fetch=download, opened_dir: Path = OPENED, wait: float = 6.0,
                 fetch_reply=download_reply, plug=None, settle: float = 1.5, tv_for=None, printer_for=None,
                 device_list=None, robot_for=None, app_map=None, find=None, ir_for=None, bt_adapters=None,
                 sphero_for=None):
        self.run, self.fetch, self.opened_dir, self.wait = runner, fetch, opened_dir, wait
        self.fetch_reply = fetch_reply
        self.plug = plug if plug is not None else devices.plug_from_env()
        self.settle = settle
        self.tv_for = tv_for or (lambda d: SamsungTV(d.address, d.mac, RUN_DIR / f"tv-{d.id}.token"))
        self.printer_for = printer_for or (lambda d: Printer(d.address, d.path or "ipp/print"))
        self.device_list = device_list or devices.current  # read fresh each time: devices can be added or removed
        self.robot_for = robot_for or self._robot_for
        self.used_tokens: set[str] = set()
        self.app_map = app_map if app_map is not None else mac_map.AppMap()
        self.found = mac_map.Found()
        self.find = find or mac_map.find_files
        self.ir_for = ir_for or (lambda d: IRBlaster(d.address, d.mac, int(d.uid) if (d.uid or "").isdigit() else None))
        self.bt_adapters = bt_adapters or bluetooth.adapters  # the Mac + relays, read fresh each time
        self.sphero_for = sphero_for or (lambda d: sphero.Sphero(d.uid or d.name))
        self.levels: dict[str, int] = {}  # Bluetooth lamps: last brightness we set
        self.loop = None                   # the helper's main loop (Bluetooth runs there); set in main()

    @staticmethod
    def _robot_for(d):
        if d.id in devices.PRETENDS:
            return PretendRobot(d.id, d.sub, d.places, RUN_DIR / "pretend-robots.json")
        if d.sub == "vacuum":
            return RoborockVacuum(d.uid, d.places, RUN_DIR / "roborock.json", segments={s[0]: int(s[1]) for s in d.spots})
        return RosRobot(d.address, d.port or 9090, d.spots, RUN_DIR / f"ros-{d.id}.json")

    def photo(self) -> bytes | None:
        """One photo from the Mac camera (skips the first frames while the camera adjusts), or None."""
        shot = RUN_DIR / "camera.jpg"
        shot.parent.mkdir(parents=True, exist_ok=True)
        shot.unlink(missing_ok=True)
        r = self.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "avfoundation", "-framerate", "30",
                      "-i", f"{CAMERA}:none", "-vf", "select=gte(n\\,20)", "-frames:v", "1", str(shot)], timeout=15)
        if r.returncode != 0 or not shot.exists():
            return None
        return shot.read_bytes()

    def device(self, msg: dict) -> dict:
        """Run one allowed action on one added device, then prove it."""
        result = {"type": "result", "command_id": msg.get("command_id"), "ok": False}
        dev = next((d for d in self.device_list() if d.id == msg.get("device_id")), None)
        action = msg.get("action")
        if msg.get("type") != "device" or dev is None:
            return result | {"detail": "Refused: not a device in the list"}
        if action not in dev.actions:
            return result | {"detail": f"Refused: a {dev.kind} can't do that"}
        if not re.fullmatch(r"[0-9a-f]{12}", str(msg.get("command_id", ""))):
            return result | {"detail": "Refused: bad command id"}
        result["device"] = dev.id
        if dev.kind == "tv":
            return self.tv(dev, action, result)
        if dev.kind == "printer":
            return self.print_file(dev, msg, result)
        if dev.kind == "robot" and dev.sub == "sphero":
            return self.sphero(dev, action, msg.get("arg"), result)
        if dev.kind == "robot":
            return self.robot(dev, action, msg.get("arg"), result)
        if dev.kind == "ir":
            return self.press(dev, action, result)
        if dev.kind == "ble_lamp":
            return self.bt_lamp(dev, action, msg.get("arg"), result)
        if dev.kind == "switchbot":
            return self.bot(dev, action, result)
        return self.switch(dev, action, result)

    # ---- Bluetooth (the Mac's own, or a relay) ----
    def _await(self, coro, timeout: float = 40):
        """Run a Bluetooth job on the helper's main loop (macOS Bluetooth prefers one loop), or its own in tests."""
        import threading
        loop = self.loop
        if loop and loop.is_running() and getattr(loop, "_thread_id", None) != threading.get_ident():
            return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)
        return asyncio.run(coro)

    def _adapter(self, dev):
        return bluetooth.adapter_for(dev.via, self.bt_adapters())

    def bt_scan(self, msg: dict) -> dict:
        out = {"type": "bt_found", "request_id": msg.get("request_id"), "items": [], "problems": []}
        if msg.get("type") != "bt_scan" or not re.fullmatch(r"[0-9a-f]{12}", str(msg.get("request_id", ""))):
            return out | {"problems": ["Refused"]}
        try:
            items, problems = self._await(bluetooth.scan(8, self.bt_adapters()), timeout=30)
        except bluetooth.BluetoothError as e:
            return out | {"problems": [str(e)]}
        except Exception as e:
            return out | {"problems": [f"Bluetooth: {type(e).__name__} (allow Bluetooth for Terminal in System Settings)"]}
        return out | {"items": items, "problems": problems}

    def camera_check(self, action: str, do, result: dict, what: str) -> dict:
        """Photo, do it, photo: proof for devices that can't report back (infrared, cheap Bluetooth lamps)."""
        before = self.photo()
        try:
            do()
        except Exception as e:
            return result | {"detail": f"Couldn't do it: {e}"}
        time.sleep(self.settle)
        after = self.photo()
        if before is None or after is None:
            return result | {"ok": True, "confirmed": False,
                             "detail": f"{what}. It can't report back, and the camera couldn't take a photo"}
        (m0, w0), (m1, w1) = brightness(before), brightness(after)
        up = m1 - m0 >= BRIGHTER or w1 - w0 >= BRIGHT_SHARE
        down = m0 - m1 >= BRIGHTER or w0 - w1 >= BRIGHT_SHARE
        seen = up if action in ("on", "brighter") else down if action in ("off", "dimmer") else (up or down)
        result["proof_b64"] = base64.b64encode(side_by_side(before, after)).decode()
        change = f"brightness {m0:.0f} → {m1:.0f}"
        if action in ("on", "off") and seen:
            result["state"] = action == "on"
        if not seen:
            return result | {"ok": True, "confirmed": False, "detail": f"{what}, but the camera saw no change ({change})"}
        return result | {"ok": True, "confirmed": True, "detail": f"{what} and the camera saw it ({change})"}

    def bt_lamp(self, dev, action: str, colour: str | None, result: dict) -> dict:
        if action == "colour" and not ble_lamp.colour_name(colour):
            return result | {"detail": f"Refused: pick a colour ({', '.join(ble_lamp.COLOURS)})"}
        level = ble_lamp.next_level(self.levels.get(dev.id, 100), action) if action in ("brighter", "dimmer") else 100
        lamp = ble_lamp.BleLamp(self._adapter(dev), dev.address, dev.path or "elk")

        def do():
            self._await(lamp.do(action, colour, level))
            if action in ("brighter", "dimmer"):
                self.levels[dev.id] = level
        what = f"Sent {action}" + (f" {ble_lamp.colour_name(colour)}" if action == "colour" else "") + \
            (f" (brightness {level}%)" if action in ("brighter", "dimmer") else "")
        return self.camera_check(action, do, result, what)

    def bot(self, dev, action: str, result: dict) -> dict:
        try:
            r = self._await(switchbot.SwitchBot(self._adapter(dev), dev.address).do(action))
        except Exception as e:
            return result | {"detail": f"Couldn't reach the SwitchBot: {e}"}
        out = result | {"ok": True, "confirmed": r["confirmed"], "detail": r["detail"]}
        if r["confirmed"] and action in ("on", "off"):
            out["state"] = action == "on"
        return out

    def sphero(self, dev, action: str, colour: str | None, result: dict) -> dict:
        rgb = ble_lamp.COLOURS.get(ble_lamp.colour_name(colour) or "") if action == "colour" else None
        if action == "colour" and not rgb:
            return result | {"detail": "Refused: pick a colour"}
        try:
            r = self.sphero_for(dev).do(action, rgb)
        except Exception as e:
            return result | {"detail": f"Couldn't use the robot: {e}", "problem": str(e)}
        return result | r

    def press(self, dev, button: str, result: dict) -> dict:
        """Press one learned remote button through the IR blaster, then look with the camera: infrared can't
        report back, so the camera is the only proof."""
        code = dev.code_for(button)
        if not code:
            return result | {"detail": f"Refused: the {button} button hasn't been taught"}
        before = self.photo()
        try:
            self.ir_for(dev).send(code)
        except IRError as e:
            return result | {"detail": f"Couldn't use the IR blaster: {e}"}
        time.sleep(self.settle)
        after = self.photo()
        if before is None or after is None:
            return result | {"ok": True, "confirmed": False,
                             "detail": f"Pressed {button}. Infrared can't report back, and the camera couldn't take a photo"}
        (m0, w0), (m1, w1) = brightness(before), brightness(after)
        up = m1 - m0 >= BRIGHTER or w1 - w0 >= BRIGHT_SHARE
        down = m0 - m1 >= BRIGHTER or w0 - w1 >= BRIGHT_SHARE
        seen = up if button in ("on", "brighter") else down if button in ("off", "dimmer") else (up or down)
        result["proof_b64"] = base64.b64encode(side_by_side(before, after)).decode()
        change = f"brightness {m0:.0f} → {m1:.0f}"
        if button in ("on", "off") and seen:
            result["state"] = button == "on"
        if not seen:
            return result | {"ok": True, "confirmed": False, "detail": f"Pressed {button}, but the camera saw no change ({change})"}
        return result | {"ok": True, "confirmed": True, "detail": f"Pressed {button} and the camera saw it ({change})"}

    def tv(self, dev, action: str, result: dict) -> dict:
        r = self.tv_for(dev).do(action)
        keep = {k: r[k] for k in ("ok", "confirmed", "detail", "state", "before", "after", "muted", "app") if k in r}
        return result | keep

    def front_app(self) -> str:
        """The name of the app in front, from lsappinfo (built into macOS; no permission needed)."""
        r = self.run(["lsappinfo", "info", "-only", "name", "front"])
        if r.returncode != 0 or not r.stdout:
            r = self.run(["sh", "-c", 'lsappinfo info -only name "$(lsappinfo front)"'])
        m = re.search(r'"(?:LSDisplayName|name)"\s*=\s*"([^"]+)"', r.stdout or "")
        return m.group(1) if m else ""

    def open_app(self, msg: dict) -> dict:
        """Open one app from the approved list. Only an app key and plain text come from the hub; the command
        itself is built from the list here."""
        result = {"type": "result", "command_id": msg.get("command_id"), "ok": False}
        app = apps.APPS.get(str(msg.get("app")))
        if msg.get("type") != "app" or app is None or not app.on_mac:
            return result | {"detail": "Refused: not an app on the approved list"}
        if any(k in msg for k in ("link", "url", "cmd", "command", "path")):
            return result | {"detail": "Refused: apps are opened only from the list"}
        if not re.fullmatch(r"[0-9a-f]{12}", str(msg.get("command_id", ""))):
            return result | {"detail": "Refused: bad command id"}
        text = msg.get("text")
        if text is not None and (not isinstance(text, str) or len(text) > 1000):
            return result | {"detail": "Refused: the text must be plain and at most 1,000 characters"}
        if self.run(apps.mac_command(app.key, text)).returncode != 0:
            return result | {"detail": f"The Mac would not open {app.name}"}
        want = apps.expected_front(app.key)
        deadline, front = time.monotonic() + min(self.wait, 6), ""
        while True:
            front = self.front_app()
            if front in want or time.monotonic() > deadline:
                break
            time.sleep(0.4)
        proof = self.screenshot()
        if front in want:
            return result | {"ok": True, "confirmed": True, "proof_b64": proof, "detail": f"{app.name} opened; {front} is in front"}
        return result | {"ok": True, "confirmed": False, "proof_b64": proof,
                         "detail": f"Opened {app.name}, but {front or 'another app'} is in front"}

    # ---- any app installed on this Mac (from the live map; opened by its exact name, no shell) ----
    def open_mac_app(self, msg: dict) -> dict:
        result = {"type": "result", "command_id": msg.get("command_id"), "ok": False}
        name = str(msg.get("name", ""))
        if msg.get("type") != "mac_app" or not self.app_map.has(name):
            return result | {"detail": "Refused: not an app installed on this Mac"}
        if any(k in msg for k in ("link", "url", "cmd", "command", "path")):
            return result | {"detail": "Refused: apps are opened only by name"}
        if not re.fullmatch(r"[0-9a-f]{12}", str(msg.get("command_id", ""))):
            return result | {"detail": "Refused: bad command id"}
        if self.run(["open", "-a", name]).returncode != 0:
            return result | {"detail": f"The Mac would not open {name}"}
        deadline, front = time.monotonic() + min(self.wait, 8), ""
        while True:
            front = self.front_app()
            if front.lower() == name.lower() or time.monotonic() > deadline:
                break
            time.sleep(0.4)
        proof = self.screenshot()
        if front.lower() == name.lower():
            return result | {"ok": True, "confirmed": True, "proof_b64": proof, "detail": f"{name} opened; it is in front"}
        return result | {"ok": True, "confirmed": False, "proof_b64": proof,
                         "detail": f"Opened {name}, but {front or 'another app'} is in front"}

    # ---- files anywhere in your home folder, through Spotlight (Owner only; the hub checks the role) ----
    def find_files(self, msg: dict) -> dict:
        out = {"type": "found", "request_id": msg.get("request_id"), "items": []}
        if msg.get("type") != "find" or not re.fullmatch(r"[0-9a-f]{12}", str(msg.get("request_id", ""))):
            return out | {"detail": "Refused"}
        items = []
        for p in self.find(str(msg.get("words", ""))[:120]):
            items.append({"id": self.found.add(p), "name": p.name, "folder": mac_map.label(p)})
        return out | {"items": items}

    def open_found(self, msg: dict) -> dict:
        result = {"type": "result", "command_id": msg.get("command_id"), "ok": False}
        if msg.get("type") != "open_found" or any(k in msg for k in ("path", "url", "cmd")):
            return result | {"detail": "Refused: only a file I found can be opened"}
        if not re.fullmatch(r"[0-9a-f]{12}", str(msg.get("command_id", ""))):
            return result | {"detail": "Refused: bad command id"}
        path = self.found.take(str(msg.get("found_id", "")))
        if path is None or mac_map.hidden(path) or not path.is_file():
            return result | {"detail": "Refused: not a file I just found (or it's gone)"}
        if self.run(["open", str(path)]).returncode != 0:
            return result | {"detail": "The Mac would not open the file"}
        time.sleep(min(self.wait, 2))
        front = self.front_app()
        return result | {"ok": True, "confirmed": bool(front), "proof_b64": self.screenshot(),
                         "detail": f"Opened {path.name}" + (f" in {front}" if front else "")}

    # ---- the Mac's own sound (built-in osascript; no permission needed) ----
    def _osa(self, script: str):
        return self.run(["osascript", "-e", script])

    def volume(self) -> tuple[int | None, bool | None]:
        r = self._osa("get volume settings")
        vol = re.search(r"output volume:(\d+)", r.stdout or "")
        muted = re.search(r"output muted:(true|false)", r.stdout or "")
        return (int(vol.group(1)) if vol else None), (muted.group(1) == "true" if muted else None)

    def mac(self, msg: dict) -> dict:
        result = {"type": "result", "command_id": msg.get("command_id"), "ok": False}
        op = msg.get("action")
        if msg.get("type") != "mac" or op not in ("up", "down", "mute", "unmute", "set", "get"):
            return result | {"detail": "Refused: not a Mac volume action"}
        if not re.fullmatch(r"[0-9a-f]{12}", str(msg.get("command_id", ""))):
            return result | {"detail": "Refused: bad command id"}
        before, was_muted = self.volume()
        if op == "get":  # read only: nothing changes
            if before is None:
                return result | {"detail": "Couldn't read the volume"}
            return result | {"ok": True, "confirmed": True, "before": before, "after": before, "muted": was_muted,
                             "detail": f"Volume is {before}" + (" (muted)" if was_muted else "")}
        if op in ("mute", "unmute"):
            script = f"set volume output muted {'true' if op == 'mute' else 'false'}"
        else:
            level = msg.get("level") if op == "set" else (before or 0) + (10 if op == "up" else -10)
            if not isinstance(level, int):
                return result | {"detail": "Refused: the level must be a number"}
            level = max(0, min(100, level))
            script = f"set volume output volume {level} without output muted" if op != "down" or level > 0 \
                else "set volume output volume 0"
        if self._osa(script).returncode != 0:
            return result | {"detail": "The Mac wouldn't change its volume"}
        after, muted = self.volume()
        if after is None:
            return result | {"ok": True, "confirmed": False, "detail": "Changed, but couldn't read the volume back"}
        if op == "mute":
            ok = muted is True
        elif op == "unmute":
            ok = muted is False
        elif op == "set":
            ok = after == level
        elif op == "up":
            ok = after > (before or 0) or after == 100
        else:
            ok = after < (before or 100) or after == 0
        return result | {"ok": True, "confirmed": ok, "before": before, "after": after, "muted": muted,
                         "detail": f"Volume {before} → {after}" + (" (muted)" if muted else "")}

    # ---- a website you saved (the address is read here, from run/sites.json; never sent by the hub) ----
    def open_site(self, msg: dict) -> dict:
        result = {"type": "result", "command_id": msg.get("command_id"), "ok": False}
        site = sites.get(str(msg.get("site_id", "")))
        if msg.get("type") != "site" or site is None or any(k in msg for k in ("url", "link")):
            return result | {"detail": "Refused: not a saved website"}
        if not re.fullmatch(r"[0-9a-f]{12}", str(msg.get("command_id", ""))):
            return result | {"detail": "Refused: bad command id"}
        try:
            url = sites.check_url(site["url"])
        except sites.SiteError as e:
            return result | {"detail": f"Refused: {e}"}
        if self.run(["open", url]).returncode != 0:
            return result | {"detail": "The Mac would not open the website"}
        deadline, front = time.monotonic() + min(self.wait, 6), ""
        while True:
            front = self.front_app()
            if front in apps.BROWSERS or time.monotonic() > deadline:
                break
            time.sleep(0.4)
        proof = self.screenshot()
        if front in apps.BROWSERS:
            return result | {"ok": True, "confirmed": True, "proof_b64": proof, "detail": f"{site['name']} opened in {front}"}
        return result | {"ok": True, "confirmed": False, "proof_b64": proof,
                         "detail": f"Opened {site['name']}, but {front or 'another app'} is in front"}

    def robot(self, dev, action: str, place: str | None, result: dict) -> dict:
        if action in ("clean", "goto") and place not in dev.place_names:
            return result | {"detail": f"Refused: the robot has no room or spot called {place}"}
        r = self.robot_for(dev).do(action, place if action in ("clean", "goto") else None)
        keep = ("ok", "confirmed", "detail", "state", "battery", "place", "target", "problem")
        return result | {k: r[k] for k in keep if k in r}

    def print_file(self, dev, msg: dict, result: dict) -> dict:
        rec = BY_ID.get(msg.get("file_id"))
        if rec is None or rec.filename != msg.get("filename") or not SAFE_NAME.match(msg.get("filename", "")):
            return result | {"detail": "Refused: not a file in Records"}
        if not msg.get("token") or msg["token"] in self.used_tokens:
            return result | {"detail": "Refused: token missing or already used"}
        self.used_tokens.add(msg["token"])
        try:
            pdf = self.fetch(rec.id, msg["token"])
        except Exception as e:
            return result | {"detail": f"Could not get the file: {type(e).__name__}"}
        try:
            r = self.printer_for(dev).print_pdf(pdf, rec.title)
        except PrinterError as e:
            return result | {"detail": f"Printer: {e}"}
        return result | {k: r[k] for k in ("ok", "confirmed", "detail", "problems", "job") if k in r}

    def plug_for(self, dev):
        if dev.id == devices.LAMP.id:
            return self.plug
        user, pw = os.environ.get("TAPO_USERNAME"), os.environ.get("TAPO_PASSWORD")
        if not (user and pw):
            raise PlugError("add TAPO_USERNAME and TAPO_PASSWORD to .env")
        return TapoPlug(dev.address, user, pw)

    def switch(self, dev, action: str, result: dict) -> dict:
        """Switch a plug on or off, then prove it: plug state + before/after camera photo."""
        try:
            plug = self.plug_for(dev)
        except PlugError as e:
            return result | {"detail": f"Can't use the plug yet: {e}"}
        want = action == "on"
        result |= {"plug": plug.kind}
        before = self.photo() if plug.real else None
        try:
            state = plug.set(want)
        except PlugError as e:
            return result | {"detail": f"Couldn't reach the plug ({e})"}
        if state != want:
            return result | {"state": state, "detail": f"The plug says it is still {'on' if state else 'off'}"}
        result |= {"state": state}
        if not plug.real:
            return result | {"ok": True, "confirmed": True, "detail": f"Pretend plug switched {action} (no camera check)"}
        time.sleep(self.settle)
        after = self.photo()
        if before is None or after is None:
            return result | {"ok": True, "confirmed": False,
                             "detail": f"Plug is {action}, but the camera couldn't take a photo (allow Camera for Terminal)"}
        (m0, w0), (m1, w1) = brightness(before), brightness(after)
        sign = 1 if want else -1
        seen = sign * (m1 - m0) >= BRIGHTER or sign * (w1 - w0) >= BRIGHT_SHARE
        result["proof_b64"] = base64.b64encode(side_by_side(before, after)).decode()
        change = f"brightness {m0:.0f} → {m1:.0f}"
        if not seen:
            return result | {"ok": True, "confirmed": False, "detail": f"Plug is {action}, but the camera saw no change ({change})"}
        return result | {"ok": True, "confirmed": True, "detail": f"Plug is {action} and the camera saw it ({change})"}

    def speak(self, msg: dict) -> dict:
        """Play one of the hub's spoken replies through the Mac's speakers (afplay). Nothing else."""
        rid = str(msg.get("reply_id", ""))
        out = {"type": "spoken", "reply_id": rid, "ok": False}
        if msg.get("type") != "speak" or not re.fullmatch(r"[0-9a-f]{10}", rid):
            return out | {"detail": "Refused: not a reply id"}
        if not msg.get("token") or msg["token"] in self.used_tokens:
            return out | {"detail": "Refused: token missing or already used"}
        self.used_tokens.add(msg["token"])
        try:
            audio = self.fetch_reply(rid, msg["token"])
        except Exception as e:
            return out | {"detail": f"Could not get the reply: {e}"}
        path = self.opened_dir.parent / "replies" / f"{rid}.m4a"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        ok = self.run(["afplay", str(path)], timeout=30).returncode == 0
        return out | {"ok": ok, "detail": "Played on the Mac" if ok else "afplay failed"}

    def check(self, msg: dict) -> str | None:
        """Why this message must be refused, or None if it is fine."""
        if msg.get("type") != "open_file":
            return "I only open files"
        shared = SHARED_NAME.match(str(msg.get("filename", "")))
        if shared:
            if shared.group(1) != msg.get("file_id"):
                return "File name does not match the shared file"
        elif msg.get("file_id") not in BY_ID:
            return "Not a file in Records"
        elif BY_ID[msg["file_id"]].filename != msg.get("filename") or not SAFE_NAME.match(msg.get("filename", "")):
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
        if path.suffix != ".pdf":  # Word or text: the Mac's default app; we can't ask it what is open
            if self.run(["open", str(path)]).returncode != 0:
                return result | {"detail": "The Mac would not open the file"}
            time.sleep(min(self.wait, 2))
            return result | {"ok": True, "confirmed": False, "proof_b64": self.screenshot(),
                             "detail": "Opened with the Mac's default app (it can't be asked what is open)"}
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
    helper.app_map.watch()  # installs and deletes are noticed at once
    print("  Diwan Helper: connecting to the hub on this Mac…", flush=True)
    while True:
        try:
            token = (RUN_DIR / "helper-token").read_text().strip()  # read each time: a restarted hub has a new one
            async with websockets.connect(f"ws://{HUB}/helper/ws?token={token}") as ws:
                print("  Diwan Helper: connected. Waiting for commands.", flush=True)
                await ws.send(json.dumps({"type": "map", "apps": helper.app_map.names()}))
                loop = asyncio.get_running_loop()
                helper.loop = loop
                import threading
                loop._thread_id = threading.get_ident()

                def changed(added, removed, ws=ws, loop=loop):  # from the watcher thread, the moment it happens
                    print(f"  Diwan Helper: apps added {added}, removed {removed}", flush=True)
                    asyncio.run_coroutine_threadsafe(
                        ws.send(json.dumps({"type": "map", "added": added, "removed": removed})), loop)
                helper.app_map.on_change = changed
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "find":
                        async def look(m=msg):
                            await ws.send(json.dumps(await asyncio.to_thread(helper.find_files, m)))
                        asyncio.create_task(look())
                        continue
                    if msg.get("type") == "bt_scan":
                        async def listen(m=msg):
                            print("  Diwan Helper: listening for Bluetooth devices…", flush=True)
                            await ws.send(json.dumps(await asyncio.to_thread(helper.bt_scan, m)))
                        asyncio.create_task(listen())
                        continue
                    if msg.get("type") == "speak":
                        # play in the background so a long reply never holds up the next command
                        async def play(m=msg):
                            r = await asyncio.to_thread(helper.speak, m)
                            print(f"  Diwan Helper: {r['detail']}", flush=True)
                            await ws.send(json.dumps(r))
                        asyncio.create_task(play())
                        continue
                    kind = msg.get("type")
                    is_device = kind == "device"
                    what = f"{msg.get('action')} on {msg.get('device_id')}" if is_device else \
                        f"open the app {msg.get('app')}" if kind == "app" else f"Mac volume {msg.get('action')}" \
                        if kind == "mac" else f"open the website {msg.get('site_id')}" if kind == "site" \
                        else f"open the app {msg.get('name')}" if kind == "mac_app" else "open a found file" \
                        if kind == "open_found" else f"open {msg.get('file_id')}"
                    print(f"  Diwan Helper: asked to {what}", flush=True)

                    # each command runs on its own, so "stop" is never stuck behind a robot that is still driving
                    async def work(m=msg, is_device=is_device, kind=kind):
                        try:
                            job = {"device": helper.device, "app": helper.open_app, "mac": helper.mac,
                                   "site": helper.open_site, "mac_app": helper.open_mac_app,
                                   "open_found": helper.open_found}.get(kind, helper.open_file)
                            result = await asyncio.to_thread(job, m)
                        except Exception as e:  # never leave the hub waiting
                            result = {"type": "result", "command_id": m.get("command_id"), "ok": False,
                                      "detail": f"Helper error: {type(e).__name__}"}
                        print(f"  Diwan Helper: {result['detail']}", flush=True)
                        await ws.send(json.dumps(result))
                    asyncio.create_task(work())
        except (OSError, Exception) as e:  # hub not up yet, or it restarted
            print(f"  Diwan Helper: hub not reachable ({type(e).__name__}); retrying in 2 s", flush=True)
            await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
