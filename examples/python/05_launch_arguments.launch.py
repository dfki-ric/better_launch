#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this


@launch_this
def handle_with_care(enable: bool = False):
    """
    When writing a better_launch launch file, every argument of your launch function will be exposed on the command line. When running the launch file either directly or via `bl` you can pass this argument as follows:

    .. code:: bash

        bl better_launch 05_launch_arguments.py --enable True

    These arguments can be used directly in your launch code without the need for conditions and substitutions. And in case you want to know what your launch file can actually do, you can always pass `--help` to it - try it out!

    Parameters
    ----------
    enable : bool, optional
        Whether to start the listener node.
    """
    bl = BetterLaunch()

    if not enable:
        # Can also pass logging.ERROR instead of a string for the severity
        bl.log("error", "This launch file must be run with `--enable True`!")

    if bl.is_included():
        # For example 06
        bl.log("warning", f"Example 05 was included by {bl.launchfile}")

    if enable:
        bl.node(
            "examples_rclpy_minimal_publisher",
            "publisher_local_function",
            "my_talker",
        )

        # Yay, no more clunky condition substitutions!
        bl.node(
            "examples_rclpy_minimal_subscriber",
            "subscriber_member_function",
            "my_listener",
        )
