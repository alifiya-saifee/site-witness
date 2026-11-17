"""Robots: what every robot connector has in common, and the pretend robots.

Each robot connector has the same calls:
  status() -> {state, battery, place, problem}
  do(action, place=None) -> {ok, confirmed, detail, state, battery, place, problem}
Actions: stop, pause, dock, start, clean (a room) for vacuums; stop, dock, goto (a spot) for ROS robots.
A result is only "confirmed" when the robot itself reports the expected state afterwards.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

# robot state -> plain words (Roborock's own state names; ROS uses a few of the same)
STATE_WORDS = {
    "cleaning": "cleaning", "segment_cleaning": "cleaning a room", "zoned_cleaning": "cleaning", "starting": "starting",
    "returning_home": "going home to charge", "docking": "docking", "charging": "charging", "charging_complete": "charged",
    "paused": "paused", "idle": "idle", "error": "has a problem", "going_to_target": "on its way",
    "device_offline": "offline", "emptying_the_bin": "emptying its bin", "moving": "on its way", "arrived": "arrived",
}
EXPECT = {  # what the robot must report after each action for it to count as done
    "start": {"cleaning", "segment_cleaning", "starting", "zoned_cleaning"},
    "clean": {"segment_cleaning", "cleaning", "starting"},
    "pause": {"paused"},
    "stop": {"idle", "paused", "charging", "charging_complete", "arrived"},
    "dock": {"returning_home", "docking", "charging", "charging_complete", "moving", "arrived"},
    "goto": {"arrived"},
}


def plain(state: str | None) -> str:
    return STATE_WORDS.get(state or "", (state or "unknown").replace("_", " "))


def follow(read, action: str, wait: float, sleep=time.sleep, every: float = 1.0, clock=time.monotonic) -> dict:
    """Ask the robot until it reports what the action should lead to, or time runs out."""
    deadline = clock() + wait
    while True:
        st = read()
        if st.get("problem"):
            return st | {"ok": False, "confirmed": False, "detail": f"The robot says: {st['problem']}"}
        if st.get("state") in EXPECT[action]:
            return st | {"ok": True, "confirmed": True, "detail": f"The robot says: {plain(st['state'])}"}
        if clock() > deadline:
            return st | {"ok": True, "confirmed": False, "detail": f"Sent; the robot still says: {plain(st.get('state'))}"}
        sleep(every)


STATE_LOCK = threading.RLock()  # pretend robots share one state file; two stops at once must not undo each other


class PretendRobot:
    """A robot on the screen only (no hardware). It changes state over a few seconds like a real one."""
    real = False

    def __init__(self, device_id: str, sub: str, places, path: Path, travel: float = 3.0, wait: float = 8.0,
                 sleep=time.sleep, clock=time.time):
        self.id, self.sub, self.places = device_id, sub, [p[0] for p in places]
        self.path, self.travel, self.wait, self.sleep, self.clock = path, travel, wait, sleep, clock

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text()).get(self.id) or {}
        except (OSError, ValueError):
            return {}

    def _save(self, st: dict) -> None:
        try:
            allst = json.loads(self.path.read_text())
        except (OSError, ValueError):
            allst = {}
        allst[self.id] = st
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(allst))

    def status(self) -> dict:
        with STATE_LOCK:
            return self._status()

    def _status(self) -> dict:
        st = self._load() or {"state": "charging" if self.sub == "vacuum" else "arrived", "place": "Dock" if self.sub == "ros" else None}
        if st.get("until") and self.clock() >= st["until"]:  # the trip is over
            if st["state"] == "returning_home":
                st = {"state": "charging", "place": None}
            elif st["state"] == "moving":
                st = {"state": "arrived", "place": st.get("target")}
            self._save(st)
        return {"state": st["state"], "battery": 80, "place": st.get("place"), "target": st.get("target"), "problem": None}

    def do(self, action: str, place: str | None = None) -> dict:
        with STATE_LOCK:
            bad = self._change(action, place)
        if bad:
            return bad
        r = follow(self.status, action, self.wait, self.sleep, every=0.5, clock=self.clock)
        if action == "goto" and r.get("state") == "arrived" and r.get("place") != place:
            return r | {"confirmed": False, "detail": "Stopped before getting there"}
        if action == "goto" and r.get("state") == "idle":
            return r | {"confirmed": False, "detail": "Stopped before getting there"}
        return r | {"detail": r["detail"] + " (pretend robot)"}

    def _change(self, action: str, place: str | None) -> dict | None:
        now = self.clock()
        if action == "stop":
            cur = self._status()
            self._save({"state": "idle" if cur["state"] not in ("charging", "arrived") else cur["state"],
                        "place": cur["place"] if cur["state"] == "arrived" else None})
        elif action == "pause":
            self._save({"state": "paused"})
        elif action == "start":
            self._save({"state": "cleaning"})
        elif action == "clean":
            self._save({"state": "segment_cleaning", "place": place})
        elif action == "dock":
            self._save({"state": "returning_home", "until": now + self.travel} if self.sub == "vacuum"
                       else {"state": "moving", "target": "Dock", "until": now + self.travel})
        elif action == "goto":
            self._save({"state": "moving", "target": place, "until": now + self.travel})
        else:
            return {"ok": False, "detail": "Refused: not a robot action"}
        return None
