#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this, LifecycleStage


@launch_this(ui=True)
def from_the_cradle_to_the_grave():
    """In this example, two separate nodes that support lifecycle management will be started:
    * lifecycle/lifecycle_talker
    * lifecycle/lifecycle_listener

    The talker will be started in the PRISTINE stage, which means that its process will be started, but the node itself will idle in its UNCONFIGURED state. Using the TUI's node menu from the sidebar, you can then ask the talker node to transition into its ACTIVE stage. The listener will already be ACTIVE once this function returns.
    """
    bl = BetterLaunch()

    # This one you can activate from the TUI
    bl.node(
        "lifecycle",
        "lifecycle_talker",
        "start_me",
        lifecycle_target=LifecycleStage.PRISTINE,
    )
    
    # Nodes will transition to ACTIVE by default (if they come up fast enough), but for the sake 
    # of this tutorial we will transition it manually
    listener = bl.node(
        "lifecycle",
        "lifecycle_listener",
        "lc_listener",
        lifecycle_target=LifecycleStage.PRISTINE,
    )

    # The only way to see from the outside if a node supports lifecycle management is to check 
    # whether it has initialized the required topics and services
    if listener.is_lifecycle_node(timeout=5.0):
        listener.lifecycle.transition(LifecycleStage.ACTIVE)
