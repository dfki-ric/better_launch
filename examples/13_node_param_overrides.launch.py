#!/usr/bin/env python3
"""
Example launch file demonstrating node parameter overrides from command line.

By default, better_launch allows you to pass any arguments from the command line.
If you use the --bl-node-param-override flag, you can also override parameters
of specific nodes by using the <node_name>.<param_name> syntax.

The node in this example declares 'period' parameter with declare_parameter(), so it can be
overridden via -p period:=<value> when launching.

Example usage:
--------------
# Default period is 1.0s
bl better_launch 13_node_param_overrides.launch.py --bl-node-param-override true

# Override period to 0.2s (fast publishing)
bl better_launch 13_node_param_overrides.launch.py --bl-node-param-override true --my_timer.period 0.2
"""

from better_launch import BetterLaunch, launch_this
import os


@launch_this
def node_param_overrides():
    bl = BetterLaunch()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    bl.node(
        package=".",
        executable=os.path.join(script_dir, "scripts", "timed_talker.py"),
        name="my_timer",
    )
