#!/usr/bin/env python3
from fnmatch import fnmatch
from better_launch import BetterLaunch, launch_this, convenience


@launch_this
def kneel_and_bag(pattern: str = "*topic*"):
    """
    This example mostly serves to raise awareness of one very nice convenience function :)
    """
    bl = BetterLaunch()

    def should_record(topic: str) -> bool:
        if not fnmatch(topic, pattern):
            print("(in a growly voice) REJECTED!", topic, pattern)
            return False

        # Just some example code to select topics of type std_msgs/String
        topics_and_types = dict(bl.shared_node.get_topic_names_and_types())

        for tp in topics_and_types.get(topic, []):
            if tp == "std_msgs/msg/String":
                return True
        
        return False

    bl.node(
        "examples_rclpy_minimal_publisher",
        "publisher_local_function",
        "my_talker",
    )

    # Record all topics that fulfill the should_record predicate
    convenience.record_topics(
        None,
        should_record,
        max_bag_size = 0.1,  # split after 0.1 MB
        recordings = 3,  # record 3 bags in total
    )
