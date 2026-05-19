#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this


@launch_this(ui=True)
def tis_a_hungry_function():
    """
    better_launch can include other launch files and pass arbitrary arguments to them. 
    
    You can also include ROS2 launch files (.py, .yaml, .xml). Be aware though that including ROS2 launch files requires running an instance of the ROS2 launch service, which creates a lot of overhead. If possible it is always better to stick to only one launch system. This will be discussed more in the next example.
    """
    bl = BetterLaunch()

    # If no package is given, the current launch file's package is used. Additional keyword 
    # arguments are passed as launch arguments. We could also specify pass_launch_func_args to pass 
    # all arguments of this launch function.
    bl.include(None, "05_launch_arguments.launch.py", enable=True)

    # Since better_launch executes actions immediately, you can also interact with your nodes immediately!
    talker = bl.query_node("my_talker")
    bl.logger.info(f"""
======================
TALKER IS ALIVE: {talker.is_ros2_connected()}
======================
""")
