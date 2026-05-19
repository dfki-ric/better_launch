#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this, convenience


@launch_this
def so_comfortable():
    """
    The convenience module provides shortcuts for a couple of tasks that are common enough to be nice to have, yet too specific to include in the main API.
    """
    # Still need to instantiate BetterLaunch first
    bl = BetterLaunch()

    convenience.static_transform_publisher("world", "better_launch", (1, 1, 1))

    # Note that the rviz2 executable is in fact not a ROS2 node. Under the hood the convenience
    # function below calls bl.node(..., raw=True) to avoid passing any unexpected node arguments.
    convenience.rviz()
