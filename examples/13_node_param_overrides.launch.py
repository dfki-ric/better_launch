#!/usr/bin/env python3
"""
Demonstrates CLI node parameter overrides.

Node parameters can be overridden from the command line using dot-notation
without needing to declare them explicitly in the launch function.

Usage:
    # Run with default parameters
    bl better_launch 13_node_param_overrides.launch.py

    # Enable node overrides and update talker's timer_period parameter
    bl better_launch 13_node_param_overrides.launch.py \
        --bl_node_param_override enable \
        --my_talker.timer_period 2.0

    # Override multiple node parameters
    bl better_launch 13_node_param_overrides.launch.py \
        --bl_node_param_override enable \
        --my_talker.timer_period 0.1 \
        --my_listener.some_param value

The syntax is: --<node_name>.<param_name> <value>

Values are automatically parsed as JSON when possible (numbers, booleans, lists, dicts).
"""

from better_launch import BetterLaunch, launch_this


@launch_this
def demo():
    """
    Demo launch file showing node parameter overrides from CLI.

    Try running with:
        bl better_launch 13_node_param_overrides.launch.py \
            --bl_node_param_override enable \
            --my_talker.timer_period 2.0
    """
    bl = BetterLaunch()

    bl.node(
        "examples_rclpy_minimal_publisher",
        "publisher_local_function",
        "my_talker",
        params={"timer_period": 1.0},  # Can be overridden via --my_talker.timer_period
    )

    bl.node(
        "examples_rclpy_minimal_subscriber",
        "subscriber_member_function",
        "my_listener",
    )
