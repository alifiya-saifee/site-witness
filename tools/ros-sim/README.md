# Testing the robots without owning them

## ROS 2 robot: a real Nav2 simulation in Docker

ROS 2 Jazzy with the real Nav2 navigation stack, Nav2's light "loopback" simulated TurtleBot3 (no 3D graphics)
on the TurtleBot3 sandbox map, and rosbridge on port 9090. The ROS connector talks to it exactly as it would
to a real robot.

One-time setup (Mac): `brew install colima docker`, then `colima start --cpu 4 --memory 8`.

```
cd tools/ros-sim
docker build -t sitewitness-ros-sim .
docker run -d --name sw-ros-sim -p 9090:9090 sitewitness-ros-sim     # ready after about 40 s
cd ../.. && .venv/bin/python tools/ros-sim/check_ros_robot.py        # prints ALL GOOD when it works
```

It sends the robot to two spots (each confirmed by the robot's own position), then stops it half-way through a
third trip and checks the trip is *not* reported as arrived.

To use it from the page: on the Mac, **Add a robot → ROS 2 robot**, address `127.0.0.1`, port `9090`, spots:

```
Start: -2, -0.5, 0
Corner: 1.8, 0.5, 1.57
Far side: -0.5, 1.8, 3.14
Dock: -2, -0.5, 0
```

Then say “lab robot go to the corner” (tap Approve) or «وقف».

Stop it all: `docker rm -f sw-ros-sim` and `colima stop` (frees the 8 GB the Linux machine uses).

## Roborock: the library's own vacuum simulator

`tests/test_roborock_simulator.py` runs our Roborock connector against python-roborock's official simulator
(`roborock.testing`): the real library code runs; only Roborock's cloud and the vacuum's firmware are simulated.
It is part of the normal test suite (`.venv/bin/pytest -q`). A real vacuum still needs a real account.
