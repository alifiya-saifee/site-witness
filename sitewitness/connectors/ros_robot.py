"""A ROS 2 robot, through rosbridge (the standard WebSocket bridge, usually port 9090).

Only three things are ever sent:
- a Nav2 goal to one of the robot's named spots (action /navigate_to_pose),
- stop: Nav2's own "cancel every navigation goal" service (works from any connection; rosbridge keeps goals per
  connection, so cancelling by goal id alone would miss a trip started from another command), then zero speed,
- subscriptions to /amcl_pose and /tf, to read where the robot really is on its map (robots that localise
  with AMCL publish /amcl_pose; others, and simulators, only publish the map -> odom -> base links on /tf).
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
TF_TOPIC, TF_TYPE = "/tf", "tf2_msgs/msg/TFMessage"
BASE_FRAMES = ("base_footprint", "base_link")
VEL_TOPIC, VEL_TYPE = "/cmd_vel", "geometry_msgs/msg/Twist"
SUCCEEDED, CANCELED, ABORTED = 4, 5, 6  # ROS 2 GoalStatus
NEAR = 0.5  # metres
CANCEL_SERVICE, CANCEL_TYPE = NAV_ACTION + "/_action/cancel_goal", "action_msgs/srv/CancelGoal"
CANCEL_ALL = {"goal_info": {"goal_id": {"uuid": [0] * 16}, "stamp": {"sec": 0, "nanosec": 0}}}  # zero id + time = all


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

    def _subscribe_pose(self, ws) -> None:
        self._tf = getattr(self, "_tf", {})  # keep links already seen: map -> odom changes rarely
        self._send(ws, op="subscribe", topic=POSE_TOPIC, type=POSE_TYPE)
        self._send(ws, op="subscribe", topic=TF_TOPIC, type=TF_TYPE, throttle_rate=100)

    def _unsubscribe_pose(self, ws) -> None:
        self._send(ws, op="unsubscribe", topic=POSE_TOPIC)
        self._send(ws, op="unsubscribe", topic=TF_TOPIC)

    def pose_from(self, m: dict) -> tuple[float, float] | None:
        """The robot's map position from one rosbridge message, if it gives one."""
        if m.get("op") != "publish":
            return None
        if m.get("topic") == POSE_TOPIC:
            p = m["msg"]["pose"]["pose"]["position"]
            return p["x"], p["y"]
        if m.get("topic") == TF_TOPIC:
            for t in m["msg"].get("transforms", []):
                parent, child = t["header"]["frame_id"].lstrip("/"), t["child_frame_id"].lstrip("/")
                tr, q = t["transform"]["translation"], t["transform"]["rotation"]
                yaw = math.atan2(2 * (q["w"] * q["z"] + q["x"] * q["y"]), 1 - 2 * (q["y"] ** 2 + q["z"] ** 2))
                if parent == "map" and child == "odom":
                    self._tf["map_odom"] = (tr["x"], tr["y"], yaw)
                elif parent == "odom" and child in BASE_FRAMES:
                    self._tf["odom_base"] = (tr["x"], tr["y"], yaw)
            if "map_odom" in self._tf and "odom_base" in self._tf:
                (ax, ay, ath), (bx, by, _) = self._tf["map_odom"], self._tf["odom_base"]
                return ax + math.cos(ath) * bx - math.sin(ath) * by, ay + math.sin(ath) * bx + math.cos(ath) * by
        return None

    def _read_pose(self, ws, timeout: float = 3) -> tuple[float, float] | None:
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            try:
                m = json.loads(ws.recv(timeout=max(0.05, deadline - self.clock())))
            except TimeoutError:
                return None
            xy = self.pose_from(m)
            if xy is not None:
                return xy
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
            self._subscribe_pose(ws)
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
            self._subscribe_pose(ws)
            self._send(ws, op="send_action_goal", id=gid, action=NAV_ACTION, action_type=NAV_TYPE,
                       args=goal_msg(*self.spots[target]), feedback=False)
            deadline, last = self.clock() + self.wait, None
            while self.clock() < deadline:
                try:
                    m = json.loads(ws.recv(timeout=max(0.05, deadline - self.clock())))
                except TimeoutError:
                    break
                xy = self.pose_from(m)
                if xy is not None:
                    last = xy
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
            self._send(ws, op="call_service", id="diwan-stop", service=CANCEL_SERVICE, type=CANCEL_TYPE, args=CANCEL_ALL)
            cancelled = self._service_answer(ws, "diwan-stop")
            if gid:
                self._send(ws, op="cancel_action_goal", id=gid, action=NAV_ACTION)
            self._send(ws, op="advertise", topic=VEL_TOPIC, type=VEL_TYPE)
            for _ in range(3):
                self._send(ws, op="publish", topic=VEL_TOPIC, msg={"linear": {"x": 0.0, "y": 0.0, "z": 0.0},
                                                                    "angular": {"x": 0.0, "y": 0.0, "z": 0.0}})
            # AMCL only publishes when the pose changes, but a new subscription gets the latest one: ask twice
            self._subscribe_pose(ws)
            a = self._read_pose(ws, 2)
            time.sleep(0.8)
            self._unsubscribe_pose(ws)
            self._subscribe_pose(ws)
            b = self._read_pose(ws, 2)
        still = a is not None and b is not None and math.dist(a, b) < 0.05
        nav = {None: "Nav2 didn't answer the cancel", 0: "Nav2 cancelled its goals", 1: "Nav2 had no goal to cancel",
               2: "Nav2 had no such goal", 3: "Nav2 said the goal was already finished"}.get(cancelled, f"Nav2 answered {cancelled}")
        if a is None or b is None:
            return {"ok": True, "confirmed": False, "state": "idle", "detail": f"Stop sent ({nav}); couldn't read the robot's position"}
        return {"ok": True, "confirmed": still, "state": "idle" if still else "moving", "place": self.where(b),
                "detail": f"Stopped: {nav}, and its position isn't changing" if still else f"Stop sent ({nav}), but it is still moving"}

    def _service_answer(self, ws, call_id: str, timeout: float = 3) -> int | None:
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            try:
                m = json.loads(ws.recv(timeout=max(0.05, deadline - self.clock())))
            except TimeoutError:
                return None
            if m.get("op") == "service_response" and m.get("id") == call_id:
                return (m.get("values") or {}).get("return_code")
        return None
