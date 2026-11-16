"""Devices: the things in the room the agent may switch, who may use them, and how each one is reached.

Like Records for files: the agent can only ever touch a device listed here, and only switch it on or off.
A device that heats or moves (risky=True, for example an oven) always waits for a person's Approve tap.

How a device is reached is an adapter behind one small interface (set(on) -> state, state()):
- PretendPlug (default): an on-screen lamp, saved in run/pretend-plug.json. No hardware, no camera check.
- TapoPlug: a TP-Link Tapo P100/P110 on the Wi-Fi, through python-kasa. Settings come only from the
  environment (SW_PLUG=tapo, SW_PLUG_HOST, TAPO_USERNAME, TAPO_PASSWORD) and are never printed or logged.
- Home Assistant can slot in later as another adapter, without changing the agent.

All names here are made up (sample data).
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .records import PEOPLE, ROOT

RUN_DIR = ROOT / "run"


@dataclass(frozen=True)
class Device:
    id: str
    name: str                # how it is said: "the meeting-room lamp"
    name_ar: str
    room: str
    kind: str                # "plug"
    words: tuple[str, ...]   # what a person might call it (English and Arabic)
    roles: tuple[str, ...]   # roles allowed to switch it
    risky: bool = False      # heats or moves: always needs an Approve tap


DEVICES: tuple[Device, ...] = (
    # "النور" (light) is left out on purpose: it is also the Al Noor building's name.
    Device("room-lamp", "the meeting-room lamp", "مصباح غرفة الاجتماعات", "Meeting room", "plug",
           ("lamp", "light", "lights", "المصباح", "مصباح", "الضوء", "ضوء", "الاضاءة", "الإضاءة", "اللمبة", "لمبة"),
           ("owner", "broker")),
)
BY_DEVICE = {d.id: d for d in DEVICES}


def may_use(person_id: str, device: Device) -> bool:
    person = PEOPLE.get(person_id)
    return bool(person) and person["role"] in device.roles


# ---------------- adapters ----------------

class PlugError(Exception):
    """The plug could not be reached or did not answer."""


class PretendPlug:
    kind = "pretend"
    real = False

    def __init__(self, path: Path | None = None):
        self.path = path or RUN_DIR / "pretend-plug.json"

    def state(self) -> bool:
        try:
            return bool(json.loads(self.path.read_text()).get("on"))
        except (OSError, ValueError):
            return False

    def set(self, on: bool) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"on": bool(on)}))
        return self.state()


class TapoPlug:
    """A Tapo plug on the local Wi-Fi. The Tapo account login only unlocks the plug; the commands go
    straight to the plug's IP, not through the cloud."""
    kind = "tapo"
    real = True

    def __init__(self, host: str, username: str, password: str, timeout: int = 8):
        self.host, self._user, self._pass, self.timeout = host, username, password, timeout

    async def _do(self, on: bool | None) -> bool:
        from kasa import Discover
        dev = await Discover.discover_single(self.host, username=self._user, password=self._pass,
                                             timeout=self.timeout, discovery_timeout=self.timeout)
        if dev is None:
            raise PlugError("no plug answered at that address")
        try:
            await dev.update()
            if on is not None:
                await (dev.turn_on() if on else dev.turn_off())
                await dev.update()
            return bool(dev.is_on)
        finally:
            await dev.disconnect()

    def _run(self, on: bool | None) -> bool:
        try:
            return asyncio.run(asyncio.wait_for(self._do(on), self.timeout * 2))
        except PlugError:
            raise
        except Exception as e:  # never pass the error text on: it can echo the address or login
            raise PlugError(type(e).__name__) from None

    def state(self) -> bool:
        return self._run(None)

    def set(self, on: bool) -> bool:
        return self._run(on)


def plug_from_env(env=os.environ):
    """The adapter the settings ask for. Tapo needs all three settings; otherwise the pretend plug."""
    if env.get("SW_PLUG") == "tapo":
        host, user, pw = env.get("SW_PLUG_HOST"), env.get("TAPO_USERNAME"), env.get("TAPO_PASSWORD")
        if host and user and pw:
            return TapoPlug(host, user, pw)
    return PretendPlug()


def plug_kind(env=os.environ) -> str:
    """'tapo' or 'pretend', without connecting to anything (for the page)."""
    return plug_from_env(env).kind
