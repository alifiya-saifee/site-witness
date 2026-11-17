"""A Roborock robot vacuum, through python-roborock.

Login (once, on the Mac): Roborock emails a code to the account's address; the person types it on the Mac page.
What is kept: the account email and Roborock's login token, in run/roborock.json (readable only by you; never
logged, printed or committed). No password is ever asked for or stored.

This logs in to Roborock's cloud; the library then talks to the vacuum directly on the Wi-Fi when it can,
and through Roborock's cloud when it can't.

Commands: app_start, app_pause, app_stop, app_charge (dock), app_segment_clean (one room).
Every command is followed by reading the vacuum's own status: "done" only when it reports the expected state.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from .robots import follow

COMMANDS = {"start": "app_start", "pause": "app_pause", "stop": "app_stop", "dock": "app_charge",
            "clean": "app_segment_clean"}


class VacuumError(Exception):
    pass


def _safe(e: Exception) -> str:
    """Error type only: library messages can carry tokens or account details."""
    return type(e).__name__


# ---------------- login (Mac only) ----------------

def request_code(email: str) -> None:
    from roborock.web_api import RoborockApiClient

    async def go():
        await RoborockApiClient(email).request_code_v4()
    try:
        asyncio.run(asyncio.wait_for(go(), 30))
    except Exception as e:
        raise VacuumError(f"Roborock didn't send a code ({_safe(e)})") from None


def login(email: str, code: str, path: Path) -> None:
    from roborock.web_api import RoborockApiClient

    async def go():
        return await RoborockApiClient(email).code_login_v4(code.strip())
    try:
        user = asyncio.run(asyncio.wait_for(go(), 30))
    except Exception as e:
        raise VacuumError(f"Roborock didn't accept that code ({_safe(e)})") from None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"email": email, "user": user.as_dict()}))
    os.chmod(path, 0o600)


def saved_login(path: Path) -> dict | None:
    try:
        d = json.loads(path.read_text())
        return d if d.get("email") and d.get("user") else None
    except (OSError, ValueError):
        return None


async def _manager(path: Path):
    from roborock.data.containers import UserData
    from roborock.devices.device_manager import UserParams, create_device_manager
    d = saved_login(path)
    if not d:
        raise VacuumError("Roborock isn't logged in on this Mac yet")
    return await create_device_manager(UserParams(username=d["email"], user_data=UserData.from_dict(d["user"])))


def _room_names(rooms) -> list[tuple[int, str]]:
    out = []
    for r in getattr(rooms, "rooms", None) or []:
        name = getattr(r, "name", None) or getattr(r, "raw_name", None)
        if name and getattr(r, "segment_id", None) is not None:
            out.append((int(r.segment_id), str(name)))
    return out


def list_vacuums(path: Path) -> list[dict]:
    """The vacuums on the account, with their rooms, as scan results the page can add."""
    async def go():
        mgr = await _manager(path)
        try:
            out = []
            for dev in await mgr.get_devices():
                props = getattr(dev, "v1_properties", None)
                if props is None:
                    continue  # not a vacuum this connector knows
                rooms = []
                try:
                    await asyncio.wait_for(props.rooms.refresh(), 15)
                    rooms = _room_names(props.rooms)
                except Exception:
                    pass
                model = getattr(getattr(dev, "product", None), "model", "") or ""
                out.append({"duid": dev.duid, "label": dev.name, "model": model, "rooms": rooms})
            return out
        finally:
            await mgr.close()
    try:
        return asyncio.run(asyncio.wait_for(go(), 60))
    except VacuumError:
        raise
    except Exception as e:
        raise VacuumError(f"couldn't list the Roborock vacuums ({_safe(e)})") from None


# ---------------- one vacuum ----------------

class RoborockVacuum:
    real = True

    def __init__(self, duid: str, places, login_path: Path, segments: dict[str, int] | None = None,
                 wait: float = 20, sleep=time.sleep):
        self.duid, self.login_path, self.wait, self.sleep = duid, login_path, wait, sleep
        self.places = [p[0] for p in places]
        self.segments = segments or {}  # room name -> Roborock segment id

    async def _with_device(self, work):
        mgr = await _manager(self.login_path)
        try:
            dev = await mgr.get_device(self.duid)
            if dev is None or dev.v1_properties is None:
                raise VacuumError("that vacuum isn't on the Roborock account any more")
            return await work(dev.v1_properties)
        finally:
            await mgr.close()

    @staticmethod
    async def _status(props) -> dict:
        await props.status.refresh()
        s = props.status
        state = getattr(getattr(s, "state", None), "name", None)
        err = getattr(s, "error_code", None)
        err_name = getattr(err, "name", None)
        problem = err_name.replace("_", " ") if err_name and err_name not in ("none", "no_error") else None
        return {"state": state, "battery": getattr(s, "battery", None), "problem": problem}

    def _run(self, coro_fn, timeout: float = 30):
        try:
            return asyncio.run(asyncio.wait_for(self._with_device(coro_fn), timeout))
        except VacuumError:
            raise
        except Exception as e:
            raise VacuumError(f"couldn't reach the vacuum ({_safe(e)})") from None

    def status(self) -> dict:
        try:
            return self._run(self._status)
        except VacuumError as e:
            return {"state": "device_offline", "battery": None, "problem": str(e)}

    def do(self, action: str, place: str | None = None) -> dict:
        if action not in COMMANDS:
            return {"ok": False, "detail": "Refused: not a vacuum action"}
        params = None
        if action == "clean":
            seg = self.segments.get(place or "")
            if seg is None:
                return {"ok": False, "detail": f"The vacuum has no room called {place}"}
            params = [{"segments": [seg], "repeat": 1}]

        async def send(props):
            await props.command.send(COMMANDS[action], params)
        try:
            self._run(send)
        except VacuumError as e:
            return {"ok": False, "detail": f"Sorry: {e}"}
        r = follow(self.status, action, self.wait, self.sleep, every=2.0)
        return r | {"place": place}
