#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this


@launch_this
def per_aspera_ad_astra():
    """
    This launch file is used for the benchmarks. It's the same as the basic example, except that we start the nodes manually.
    
    Any interactions with ROS2, such as querying topics, creating services, publishers, subscribers, etc., or even just checking whether a specific node is alive, require a ROS2 node instance. better_launch instantiates this internal node on an as-needed basis. 
    
    By starting the nodes manually we avoid some checks the launcher would usually run, like whether the node is alive or if it's a lifecycle node. This avoids all ROS2 interactions, so the internal node is never started, saving some resources.
    """
    bl = BetterLaunch()

    with bl.group("basic"):
        talker = bl.node(
            "examples_rclpy_minimal_publisher",
            "publisher_local_function",
            "my_talker",
            autostart_process=False,
        )
        talker.start()
        
        listener = bl.node(
            "examples_rclpy_minimal_subscriber",
            "subscriber_member_function",
            "my_listener",
            autostart_process=False,
        )
        listener.start()

    bl.logger.info(f"This is the ROSAdapter instance: {bl._ros_adapter}")
