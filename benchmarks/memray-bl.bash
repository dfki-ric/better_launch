#!/usr/bin/bash

# Generates memray-bl.bin and the corresponding plot
# Memray shows similar memory usage for better_launch and ros2

rm -f ./results/memray/memray-bl.bin ./results/memray/memray-flamegraph-bl.html
memray run -o ./results/memray/memray-bl.bin ../../examples/11_performance.launch.py
memray flamegraph ./results/memray/memray-bl.bin
firefox ./results/memray/memray-flamegraph-bl.html
