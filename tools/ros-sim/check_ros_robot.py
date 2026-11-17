"""Drive a real ROS 2 robot (or the Nav2 simulation in tools/ros-sim) through Site Witness's ROS connector.

Usage:  .venv/bin/python tools/ros-sim/check_ros_robot.py [address] [port]
It asks the robot where it is, sends it to two spots, stops it half-way through a third trip, and prints what
the robot itself reported each time. Spots are on the TurtleBot3 sandbox map used by the simulation.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sitewitness.connectors.ros_robot import RosRobot  # noqa: E402

SPOTS = (("Start", -2.0, -0.5, 0.0), ("Corner", 1.8, 0.5, 1.57), ("Far side", -0.5, 1.8, 3.14))


def main(address: str = "127.0.0.1", port: int = 9090) -> int:
    state = Path(tempfile.mkdtemp()) / "ros.json"
    robot = RosRobot(address, port, SPOTS, state, wait=90)
    print("where is it?", robot.status())
    ok = True
    for spot in ("Corner", "Start"):
        t = time.monotonic()
        r = robot.do("goto", spot)
        print(f"go to {spot}: {r['detail']}  ({time.monotonic() - t:.0f} s, confirmed={r.get('confirmed')})")
        ok &= bool(r.get("confirmed"))
    # a trip stopped half-way must not be reported as arrived
    result = {}
    trip = threading.Thread(target=lambda: result.update(robot.do("goto", "Far side")))
    trip.start()
    time.sleep(6)
    stop = RosRobot(address, port, SPOTS, state).do("stop")
    trip.join(120)
    print(f"stop: {stop['detail']} (confirmed={stop.get('confirmed')})")
    print(f"the stopped trip: {result.get('detail')} (confirmed={result.get('confirmed')})")
    ok &= bool(stop.get("confirmed")) and not result.get("confirmed")
    print("ALL GOOD" if ok else "SOMETHING DIDN'T MATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:2] or ["127.0.0.1"]), *(int(p) for p in sys.argv[2:3])))
