"""A Wi-Fi infrared blaster (Broadlink RM4 mini / RM4 Pro): it copies a remote's buttons and plays them back, so
the Mac can work things that only have an infrared remote (a lamp, a fan, an old TV or AC).

- learn(): the blaster listens; you point the remote at it and press the button once. Its code comes back.
- send(code): the blaster plays that code, like pressing the button.

Infrared only goes one way: the blaster can't tell whether the lamp obeyed. The helper uses the Mac camera for that
(before and after), and says plainly when it couldn't see.

Needs the library `broadlink` (pip install broadlink) on the Mac with the blaster. It is loaded only when a real
blaster is used, so everything else works without it.
"""
from __future__ import annotations

import base64
import time


class IRError(RuntimeError):
    pass


def _lib():
    try:
        import broadlink  # noqa: PLC0415
    except ImportError as e:
        raise IRError("the blaster's library isn't installed yet (pip install broadlink)") from e
    return broadlink


def discover(seconds: int = 4) -> list[dict]:
    """Blasters on the Wi-Fi (empty if the library isn't installed)."""
    try:
        lib = _lib()
    except IRError:
        return []
    out = []
    for d in lib.discover(timeout=seconds):
        mac = getattr(d, "mac", b"")
        mac_s = ":".join(f"{b:02x}" for b in mac) if isinstance(mac, (bytes, bytearray)) else str(mac)
        out.append({"kind": "ir", "address": d.host[0], "mac": mac_s, "model": f"{getattr(d, 'model', '')}".strip()
                    or "Broadlink", "devtype": int(getattr(d, "devtype", 0)), "label": "IR blaster (Broadlink)"})
    return out


class IRBlaster:
    def __init__(self, address: str, mac: str | None = None, devtype: int | None = None, device=None):
        self.address, self.mac, self.devtype = address, mac, devtype
        self._dev = device  # tests pass a fake

    def _device(self):
        if self._dev is not None:
            return self._dev
        lib = _lib()
        try:
            if self.devtype and self.mac:
                dev = lib.gendevice(self.devtype, (self.address, 80), bytes.fromhex(self.mac.replace(":", "")))
            else:
                dev = lib.hello(self.address)
            dev.auth()
        except Exception as e:
            raise IRError(f"couldn't reach the blaster at {self.address} ({type(e).__name__})") from e
        self._dev = dev
        return dev

    def learn(self, wait: float = 20.0, poll: float = 0.5, sleep=time.sleep) -> str:
        """Listen for one button press. Returns the code (base64)."""
        dev = self._device()
        try:
            dev.enter_learning()
        except Exception as e:
            raise IRError(f"the blaster wouldn't start listening ({type(e).__name__})") from e
        waited = 0.0
        while waited < wait:
            sleep(poll)
            waited += poll
            try:
                data = dev.check_data()
            except Exception:  # nothing yet (the library raises until a code arrives)
                continue
            if data:
                return base64.b64encode(bytes(data)).decode()
        raise IRError(f"no button press heard in {wait:.0f} seconds; point the remote at the blaster and try again")

    def send(self, code: str) -> None:
        try:
            raw = base64.b64decode(code, validate=True)
        except Exception as e:
            raise IRError("that remote code is damaged; teach the button again") from e
        try:
            self._device().send_data(raw)
        except IRError:
            raise
        except Exception as e:
            raise IRError(f"the blaster didn't send ({type(e).__name__})") from e
