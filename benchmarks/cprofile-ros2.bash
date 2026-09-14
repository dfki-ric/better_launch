#!/bin/bash
python -m cProfile -o ./results/cprofile/ros2.profile /opt/ros/humble/bin/ros2 launch better_launch ros2_performance.launch.py
gprof2dot -f pstats ./results/cprofile/ros2.profile -o ./results/cprofile/ros2.dot
dot -Tsvg ./results/cprofile/ros2.dot -o ./results/cprofile/ros2.svg
rm ./results/cprofile/ros2.dot
