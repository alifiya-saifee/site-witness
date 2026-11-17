"""A ROS 2 robot, through rosbridge (the standard WebSocket bridge, usually port 9090).

Only three things are ever sent:
- a Nav2 goal to one of the robot's named spots (action /navigate_to_pose),
- a cancel of that goal, plus zero speed on /cmd_vel (stop),
- a subscription to /amcl_pose, to read where the robot really is.
Spots are the ones a person typed when adding the robot (name -> x, y, heading on the robot's map).
"Arrived" is only said when Nav2 reports success or the robot's own position is within 0.5 m of the spot.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path

NAV_ACTION, NAV_TYPE = "/navigate_to_pose", "nav2_msgs/action/NavigateToPose"
POSE_TOPIC, POSE_TYPE = "/amcl_pose", "geometry_msgs/msg/PoseWithCovarianceStamped"
VEL_TOPIC, VEL_TYPE = "/cmd_vel", "geometry_msgs/msg/Twist"
SUCCEEDED, CANCELED, ABORTED = 4, 5, 6  # ROS 2 GoalStatus
NEAR = 0.5  # metres


class RosError(Exception):
    pass


def goal_msg(x: float, y: float, heading: float) -> dict:
    return {"pose": {"header": {"frame_id": "map"},
                     "pose": {"position": {"x": x, "y": y, "z": 0.0},
                              "orientation": {"x": 0.0, "y": 0.0, "z": math.sin(heading / 2), "w": math.cos(heading / 2)}}}}


class RosRobot:
    real = True

    def __init__(self, address: str, port: int, spots, state_path: Path, connect=None, wait: float = 45,
                 clock=time.monotonic):
        self.url = f"ws://{address}:{port or 9090}"
        self.spots = {s[0]: (float(s[1]), float(s[2]), float(s[3])) for s in spots}
        self.state_path, self.wait, self.clock = state_path, wait, clock
        self._connect = connect or (lambda url: __import__("websockets.sync.client", fromlist=["connect"]).connect(
            url, open_timeout=5, close_timeout=2))

    # ---- the link ----
    def _open(self):
        try:
            return self._connect(self.url)
        except Exception as e:
            raise RosError(f"couldn't reach the robot's rosbridge ({type(e).__name__})") from None

    @staticmethod
    def _send(ws, **msg) -> None:
        ws.send(json.dumps(msg))

    def _read_pose(self, ws, timeout: float = 3) -> tuple[float, float] | None:
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            try:
                m = json.loads(ws.recv(timeout=max(0.05, deadline - self.clock())))
            except TimeoutError:
                return None
            if m.get("op") == "publish" and m.get("topic") == POSE_TOPIC:
                p = m["msg"]["pose"]["pose"]["position"]
                return p["x"], p["y"]
        return None

    def where(self, xy) -> str | None:
        if xy is None:
            return None
        for name, (x, y, _) in self.spots.items():
            if math.dist(xy, (x, y)) <= NEAR:
                return name
        return None

    # ---- what the hub can ask ----
    def status(self) -> dict:
        try:
            ws = self._open()
        except RosError as e:
            return {"state": "device_offline", "problem": str(e)}
        with ws:
            self._send(ws, op="subscribe", topic=POSE_TOPIC, type=POSE_TYPE)
            xy = self._read_pose(ws)
        place = self.where(xy)
        return {"state": "arrived" if place else ("idle" if xy else "unknown"), "place": place, "battery": None, "problem": None}

    def do(self, action: str, place: str | None = None) -> dict:
        try:
            if action == "stop":
                return self._stop()
            if action in ("goto", "dock"):
                target = "Dock" if action == "dock" else place
                if target not in self.spots:
                    return {"ok": False, "detail": f"The robot has no spot called {target}"}
                return self._goto(target)
        except RosError as e:
            return {"ok": False, "detail": f"Sorry: {e}"}
        return {"ok": False, "detail": "Refused: not a ROS robot action"}

    def _goto(self, target: str) -> dict:
        gid = "diwan-" + uuid.uuid4().hex[:8]
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"goal": gid}))  # so "stop" can cancel it, even from another command
        ws = self._open()
        with ws:
            self._send(ws, op="subscribe", topic=POSE_TOPIC, type=POSE_TYPE)
            self._send(ws, op="send_action_goal", id=gid, action=NAV_ACTION, action_type=NAV_TYPE,
                       args=goal_msg(*self.spots[target]), feedback=False)
            deadline, last = self.clock() + self.wait, None
            while self.clock() < deadline:
                try:
                    m = json.loads(ws.recv(timeout=max(0.05, deadline - self.clock())))
                except TimeoutError:
                    break
                if m.get("op") == "publish" and m.get("topic") == POSE_TOPIC:
                    p = m["msg"]["pose"]["pose"]["position"]
                    last = (p["x"], p["y"])
                    if self.where(last) == target:
                        return {"ok": True, "confirmed": True, "state": "arrived", "place": target,
                                "detail": f"The robot is within {NEAR} m of {target}"}
                if m.get("op") == "action_result" and m.get("id") == gid:
                    status = m.get("status")
                    if status == SUCCEEDED or m.get("result") is True and status is None:
                        return {"ok": True, "confirmed": True, "state": "arrived", "place": target,
                                "detail": f"Nav2 says it reached {target}"}
                    if status == CANCELED:
                        return {"ok": True, "confirmed": False, "state": "idle", "place": self.where(last),
                                "detail": "Stopped before getting there"}
                    return {"ok": False, "state": "error", "problem": "it couldn't find a way there",
                            "detail": f"Nav2 gave up (status {status})"}
        return {"ok": True, "confirmed": False, "state": "moving", "place": None, "target": target,
                "detail": f"Still on its way to {target}"}

    def _stop(self) -> dict:
        try:
            gid = json.loads(self.state_path.read_text()).get("goal")
        except (OSError, ValueError):
            gid = None
        ws = self._open()
        with ws:
            if gid:
                self._send(ws, op="cancel_action_goal", id=gid, action=NAV_ACTION)
            self._send(ws, op="advertise", topic=VEL_TOPIC, type=VEL_TYPE)
            for _ in range(3):
                self._send(ws, op="publish", topic=VEL_TOPIC, msg={"linear": {"x": 0.0, "y": 0.0, "z": 0.0},
                                                                    "angular": {"x": 0.0, "y": 0.0, "z": 0.0}})
            # AMCL only publishes when the pose changes, but a new subscription gets the latest one: ask twice
            self._send(ws, op="subscribe", topic=POSE_TOPIC, type=POSE_TYPE)
            a = self._read_pose(ws, 2)
            time.sleep(0.8)
            self._send(ws, op="unsubscribe", topic=POSE_TOPIC)
            self._send(ws, op="subscribe", topic=POSE_TOPIC, type=POSE_TYPE)
            b = self._read_pose(ws, 2)
        still = a is not None and b is not None and math.dist(a, b) < 0.05
        return {"ok": True, "confirmed": still, "state": "idle", "place": self.where(b),
                "detail": "Stopped: the robot's position isn't changing" if still else "Stop sent; couldn't read the robot's position"}
