#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this


@launch_this
def first_steps():
    """
    This is how nice your launch files could be!

    You can run this launch file either directly or with the included `bl` script, which should be on your PATH once you have built better_launch and sourced your workspace:

    .. code:: bash

        bl better_launch 01_basic_example.py

    NOTE: All functions come with proper documentation, which you can also find at `../docs/build/html/index.html`.
    """
    bl = BetterLaunch()

    if not bl.is_included():
        print("I am a strong, independent launchfile!")

    with bl.group("basic"):
        bl.node(
            "examples_rclpy_minimal_publisher",
            "publisher_local_function",
            "my_talker",
        )

        # Convenience and comfort at your behest :)
        msg = bl.receive_message("/basic/topic", "std_msgs/msg/String", None, timeout=5.0)
        print(f"\n### Oh hey, I received a message :D\n{msg}\n")

        bl.node(
            "examples_rclpy_minimal_subscriber",
            "subscriber_member_function",
            "my_listener",
        )
