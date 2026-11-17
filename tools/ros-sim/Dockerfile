# A real ROS 2 robot to test the ROS connector against, with no hardware:
# ROS 2 Jazzy + Nav2 (real navigation) + Nav2's loopback simulator (a light simulated TurtleBot3, no 3D graphics)
# + rosbridge (the WebSocket link the connector uses, port 9090).
FROM ros:jazzy-ros-base
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-nav2-loopback-sim \
      ros-jazzy-nav2-minimal-tb3-sim ros-jazzy-rosbridge-server \
    && rm -rf /var/lib/apt/lists/*
COPY start.sh /start.sh
RUN chmod +x /start.sh
EXPOSE 9090
CMD ["/start.sh"]
