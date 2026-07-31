#!/usr/bin/env python3

"""Generates reports/psutil_bl.csv and reports/psutil_ros2.csv

Memory and CPU usage is measured using psutil.Popen. This method will record significantly less 
memory for ROS2, possibly due to only counting residential set memory.

Use plot.py to generate the plots from the recorded csv files.

NOTE: make sure the referenced launch files are installed in your workspace and that the 
workspace is sourced!

Usage:
    python psutil_benchmark.py bl
    python psutil_benchmark.py ros2
"""

import sys
import os
import psutil
import signal
import time
import csv


COMMAND_BL = ["python", "../../examples/11_performance.launch.py"]
COMMAND_ROS2 = ["ros2", "launch", "better_launch", "ros2_performance.launch.py"]
INTERVAL = 0.1  
OUTPUT_NAME_FMT = "results/psutil/psutil_%s.csv"


def monitor_process(proc: psutil.Popen, output: str, interval: float = 0.1):
    start = time.time()
    
    with open(output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "cpu_%", "memory_mb"])
        try:
            while proc.is_running():
                cpu = proc.cpu_percent(interval=interval)
                mem_info = proc.memory_full_info()
                mem = (mem_info.uss) / (1024 * 1024)
     
                writer.writerow([time.time() - start, cpu, mem])

                if time.time() >= start + 10.0:
                    proc.send_signal(signal.SIGINT)
                    break
        except psutil.NoSuchProcess:
            print("Process ended")

    time.sleep(1.0)
    proc.terminate()
    time.sleep(1.0)
    proc.kill()


if __name__ == "__main__":
    """Usage:
    * `psutil_benchmark.py bl`
    * `psutil_benchmark.py ros2`
    * `psutil_plots.py`
    """
    if len(sys.argv) < 2:
        raise ValueError("No mode was passed")

    mode = sys.argv[1]

    if mode == "bl":
        cmd = COMMAND_BL
    elif mode == "ros2":
        cmd = COMMAND_ROS2
    else:
        raise ValueError("Invalid mode")

    process = psutil.Popen(cmd)
    output = OUTPUT_NAME_FMT % cmd[0]
    path = os.path.join(os.path.dirname(__file__), output)
    monitor_process(process, path, INTERVAL)
