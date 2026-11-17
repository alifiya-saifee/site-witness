#!/usr/bin/env bash
# Start Nav2 with the loopback simulator (TurtleBot3 sandbox map, no GUI) and rosbridge on port 9090.
# The simulator waits to be told where the robot starts (normally a click in RViz), so we publish that once.
set -e
source /opt/ros/jazzy/setup.bash
ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=9090 &
( sleep 12
  ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
    "{header: {frame_id: map}, pose: {pose: {position: {x: -2.0, y: -0.5, z: 0.0}, orientation: {w: 1.0}}}}" ) &
exec ros2 launch nav2_bringup tb3_loopback_simulation.launch.py use_rviz:=False headless:=True
