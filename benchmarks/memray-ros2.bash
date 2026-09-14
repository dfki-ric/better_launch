#!/usr/bin/bash

# Generates memray-ros2.bin and the corresponding plot
# Memray shows similar memory usage for better_launch and ros2

rm -f ./results/memray/memray-ros2.bin ./results/memray/memray-flamegraph-ros2.html
memray run -o ./results/memray/memray-ros2.bin /opt/ros/humble/bin/ros2 launch better_launch ros2_performance.launch.py
memray flamegraph ./results/memray/memray-ros2.bin
firefox ./results/memray/memray-flamegraph-ros2.html
