#!/usr/bin/env python3

"""Generates the plots from bl_profile.csv and ros2_profile.csv
"""

import os
import plotly.graph_objects as go
import pandas as pd


BENCHMARK_BL = "results/psutil/psutil_bl.csv"
BENCHMARK_ROS2 = "results/psutil/psutil_ros2.csv"


def plot_usage(bl_csv: str, ros2_csv: str):
    df1 = pd.read_csv(bl_csv)
    df2 = pd.read_csv(ros2_csv)

    fig_cpu = go.Figure()
    fig_cpu.add_trace(
        go.Scatter(x=df1["time_s"], y=df1["cpu_%"], mode="lines", name="better_launch")
    )
    fig_cpu.add_trace(
        go.Scatter(x=df2["time_s"], y=df2["cpu_%"], mode="lines", name="ros2")
    )
    fig_cpu.update_layout(
        title="CPU Usage Comparison", xaxis_title="time_s", yaxis_title="cpu_%"
    )

    fig_mem = go.Figure()
    fig_mem.add_trace(
        go.Scatter(x=df1["time_s"], y=df1["memory_mb"], mode="lines", name="better_launch")
    )
    fig_mem.add_trace(
        go.Scatter(x=df2["time_s"], y=df2["memory_mb"], mode="lines", name="ros2")
    )
    fig_mem.update_layout(
        title="Memory Usage Comparison", xaxis_title="time_s", yaxis_title="memory_mb"
    )

    fig_cpu.show()
    fig_mem.show()


if __name__ == "__main__":
    plot_usage(
        os.path.join(os.path.dirname(__file__), BENCHMARK_BL),
        os.path.join(os.path.dirname(__file__), BENCHMARK_ROS2),
    )
