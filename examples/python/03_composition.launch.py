#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this
from better_launch.elements import Component


@launch_this(ui=True)
def not_a_song():
    """
    This example will create a Composer node and load two example plugins into it from the composition package:
    * composition/composition::Talker
    * composition/composition::Listener

    Using the terminal UI (the TUI), you will see how they appear as a single node. Opening the node dialog from the sidebar will also allow you to unload individual components or kill the entire composer.
    """
    bl = BetterLaunch()

    with bl.compose("my_composer"):
        # We load the first component immediately
        # For the purpose of this tutorial we'll create the listener later
        bl.component("composition", "composition::Talker", "comp_talker")

    # bl.compose returns a Composer that we could reuse, but even without it's possible to reuse an 
    # already running composer node (even if it wasn't started with better_launch!)
    with bl.compose("my_composer", reuse_existing=True) as composer:
        # Instead of calling bl.component we can also create the Component directly
        listener = Component(
            composer, 
            package="composition", 
            plugin="composition::Listener", 
            name="comp_listener",
            namespace="/",  # must be provided for manual instantiation
        )
    
        # Two ways to start the component
        # composer.load_component(comp2) 
        listener.start()
