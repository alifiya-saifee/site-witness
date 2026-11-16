"""Smart plugs: a TP-Link Tapo P100/P110 on the Wi-Fi (python-kasa), or the pretend lamp on the page.

Both have the same two calls: set(on) -> state, state(). The Tapo login (TAPO_USERNAME / TAPO_PASSWORD, from the
environment only) just unlocks the plug; the commands go straight to the plug's IP, not through the cloud.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path


class PlugError(Exception):
    """The plug could not be reached or did not answer."""


class PretendPlug:
    kind = "pretend"
    real = False

    def __init__(self, path: Path):
        self.path = path

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
