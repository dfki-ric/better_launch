#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this


# NOTE This is the new part!
@launch_this(ui=True)
def a_nice_ui():
    """
    This example starts the same nodes as the previous one, but uses a terminal UI for display and management. Use tab/shit-tab/enter/escape to navigate the submenus and see what you can do! 

    In case some of the default keybindings don't work for you, it is possible to specify overrides as below. More information can be found in the better_tui documentation! 

    BL_TUI_KEYBINDS="nodes: c-n; loglevel: c-l" bl better_launch 02_ui.launch.py
    """
    bl = BetterLaunch()

    with bl.group("basic"):
        bl.node(
            "examples_rclpy_minimal_publisher",
            "publisher_local_function",
            "my_talker",
        )
        bl.node(
            "examples_rclpy_minimal_subscriber",
            "subscriber_member_function",
            "my_listener",
        )
