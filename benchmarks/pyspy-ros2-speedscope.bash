#!/bin/bash
py-spy record --format speedscope -o ./results/pyspy/speedscope-ros2.json -- ros2 launch better_launch ros2_performance.launch.py
