#!/bin/bash
py-spy record --format flamegraph -o ./results/pyspy/ros2.svg -- ros2 launch better_launch ros2_performance.launch.py