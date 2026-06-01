#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this


@launch_this
def stop_bugging_me():
    """
    If you want to debug a node or execute it by some other means you can do so easily through the node's `exec_args`. These will be prepended to the node's run command.
    """
    bl = BetterLaunch()

    bl.node(
        # Use the cpp version this time so gdb can actually debug it
        "examples_rclcpp_minimal_publisher",
        "publisher_member_function",
        "my_talker",
        # Strings with quoted sections will be split correctly thanks to shlex
        exec_args="xterm -e gdb -ex run --args",
    )
