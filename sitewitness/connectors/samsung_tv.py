"""A Samsung smart TV (Tizen, 2016 and later), on the same Wi-Fi.

- The first time, the TV shows an "Allow" pop-up; accept it with the TV remote. The TV then gives a token, kept in
  run/tv-<id>.token (only you can read it). It is never printed, logged or sent anywhere.
- Every action is checked by asking the TV afterwards, not assumed:
  power from GET :8001/api/v2/, volume and mute from the TV's own UPnP report (:9197), apps from the app status.
- Turning ON over Wi-Fi needs the TV setting "Power On with Mobile" (Wake-on-LAN). Without it the TV can't hear us
  when it is off, and we say so.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import httpx

APPS = {"youtube": ("YouTube", "111299001912"), "netflix": ("Netflix", "3201907018807")}
ACTIONS = ("on", "off", "volume_up", "volume_down", "mute", "app:youtube", "app:netflix", "hdmi", "pair")
STEPS = 3  # volume steps per "volume up"

UPNP = """<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
 s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:{a} xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">
<InstanceID>0</InstanceID><Channel>Master</Channel></u:{a}></s:Body></s:Envelope>"""


class TVError(Exception):
    pass


class SamsungTV:
    def __init__(self, address: str, mac: str | None, token_path: Path, remote=None, get=None, post=None,
                 wake=None, sleep=time.sleep, wait: float = 12):
        self.address, self.mac, self.token_path = address, mac, token_path
        self._remote, self._wake = remote, wake or self._wol
        self._get = get or (lambda url: httpx.get(url, timeout=3).json())
        self._post = post or (lambda url, body, headers: httpx.post(url, content=body, headers=headers, timeout=3).text)
        self.sleep, self.wait = sleep, wait

    # ---- reading the TV ----
    def power(self) -> str:
        """'on', 'standby' or 'off' (not answering at all)."""
        try:
            return self._get(f"http://{self.address}:8001/api/v2/").get("device", {}).get("PowerState", "on")
        except Exception:
            return "off"

    def _upnp(self, action: str, field: str) -> int | None:
        try:
            text = self._post(f"http://{self.address}:9197/upnp/control/RenderingControl1", UPNP.format(a=action),
                              {"Content-Type": 'text/xml; charset="utf-8"',
                               "SOAPAction": f'"urn:schemas-upnp-org:service:RenderingControl:1#{action}"'})
            m = re.search(rf"<{field}>(\d+)</{field}>", text)
            return int(m.group(1)) if m else None
        except Exception:
            return None

    def volume(self) -> int | None:
        return self._upnp("GetVolume", "CurrentVolume")

    def muted(self) -> bool | None:
        v = self._upnp("GetMute", "CurrentMute")
        return None if v is None else bool(v)

    # ---- talking to the TV ----
    def remote(self):
        if self._remote is None:
            from samsungtvws import SamsungTVWS
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self._remote = SamsungTVWS(self.address, port=8002, token_file=str(self.token_path), timeout=30,
                                       key_press_delay=0.25, name="Diwan")
        return self._remote

    def _key(self, key: str, times: int = 1) -> None:
        try:
            for _ in range(times):
                self.remote().send_key(key)
        except Exception as e:  # the type only: the library's messages can carry the token
            raise TVError(f"the TV didn't take the command ({type(e).__name__}). "
                          "If an 'Allow' pop-up is on the TV, accept it") from None
        finally:
            self._lock_token()

    def _lock_token(self) -> None:
        if self.token_path.exists():
            os.chmod(self.token_path, 0o600)

    def _wol(self, mac: str) -> None:
        from wakeonlan import send_magic_packet
        send_magic_packet(mac)

    def _until(self, test, wait: float | None = None) -> bool:
        deadline = time.monotonic() + (self.wait if wait is None else wait)
        while True:
            if test():
                return True
            if time.monotonic() > deadline:
                return False
            self.sleep(0.8)

    # ---- the actions (each returns ok / confirmed / detail, plus numbers for the reply) ----
    def do(self, action: str) -> dict:
        if action not in ACTIONS:
            return {"ok": False, "detail": "Refused: not a TV action"}
        try:
            return getattr(self, "_" + action.replace(":", "_"))()
        except TVError as e:
            return {"ok": False, "detail": f"Sorry: {e}"}

    def _pair(self) -> dict:
        if self.power() != "on":
            return {"ok": False, "detail": "Turn the TV on first, then add it again"}
        try:
            self.remote().open()
        except Exception as e:
            raise TVError(f"the TV didn't allow it ({type(e).__name__})") from None
        finally:
            self._lock_token()
        ok = self.token_path.exists() and self.token_path.stat().st_size > 0
        return {"ok": ok, "confirmed": ok, "detail": "The TV allowed Diwan" if ok else
                "The TV didn't give a token. Accept 'Allow' on the TV and add it again"}

    def _off(self) -> dict:
        if self.power() != "on":
            return {"ok": True, "confirmed": True, "state": False, "detail": "The TV was already off"}
        self._key("KEY_POWER")
        ok = self._until(lambda: self.power() != "on")
        return {"ok": True, "confirmed": ok, "state": False if ok else None,
                "detail": "TV is off (the TV says standby)" if ok else "Sent off, but the TV still says it is on"}

    def _on(self) -> dict:
        if self.power() == "on":
            return {"ok": True, "confirmed": True, "state": True, "detail": "The TV was already on"}
        if self.mac:
            self._wake(self.mac)
        if self.power() == "standby":  # some TVs still listen in standby
            try:
                self._key("KEY_POWER")
            except TVError:
                pass
        ok = self._until(lambda: self.power() == "on", wait=self.wait * 1.5)  # a TV takes a while to boot
        if ok:
            return {"ok": True, "confirmed": True, "state": True, "detail": "TV is on (the TV says on)"}
        return {"ok": False, "detail": "The TV didn't wake up. Switch on 'Power On with Mobile' in the TV's "
                "Settings → General → Network → Expert Settings"}

    def _volume(self, key: str, sign: int) -> dict:
        v0 = self.volume()
        self._key(key, STEPS)
        if v0 is not None:  # give the TV a moment to report the new level
            self._until(lambda: sign * ((self.volume() or v0) - v0) > 0, wait=3)
        v1 = self.volume()
        if v0 is None or v1 is None:
            return {"ok": True, "confirmed": False, "detail": "Sent, but the TV didn't report its volume"}
        ok = sign * (v1 - v0) > 0
        return {"ok": True, "confirmed": ok, "before": v0, "after": v1,
                "detail": f"Volume {v0} → {v1}" if ok else f"Volume stayed at {v1}"}

    def _volume_up(self) -> dict:
        return self._volume("KEY_VOLUP", 1)

    def _volume_down(self) -> dict:
        return self._volume("KEY_VOLDOWN", -1)

    def _mute(self) -> dict:
        m0 = self.muted()
        self._key("KEY_MUTE")
        self.sleep(0.8)
        m1 = self.muted()
        if m0 is None or m1 is None:
            return {"ok": True, "confirmed": False, "detail": "Sent mute, but the TV didn't report it"}
        ok = m1 != m0
        return {"ok": True, "confirmed": ok, "muted": m1,
                "detail": ("Muted" if m1 else "Sound back on") if ok else "The TV's mute didn't change"}

    def _app(self, key: str) -> dict:
        name, app_id = APPS[key]
        try:
            self.remote().rest_app_run(app_id)
        except Exception as e:
            raise TVError(f"the TV wouldn't start {name} ({type(e).__name__})") from None
        finally:
            self._lock_token()

        def visible():
            try:
                return bool(self.remote().rest_app_status(app_id).get("visible"))
            except Exception:
                return False
        ok = self._until(visible)
        return {"ok": True, "confirmed": ok, "app": name,
                "detail": f"{name} is open on the TV (the TV says visible)" if ok else f"Asked for {name}, but the TV doesn't show it yet"}

    def _app_youtube(self) -> dict:
        return self._app("youtube")

    def _app_netflix(self) -> dict:
        return self._app("netflix")

    def _hdmi(self) -> dict:
        self._key("KEY_HDMI")
        return {"ok": True, "confirmed": False, "detail": "Switched input. The TV doesn't report which input is on"}
