#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this
import time

# This is what we usually want to avoid, but for the sake of this tutorial...
from launch_ros.actions import Node
from launch.actions import ExecuteProcess, TimerAction
from launch.conditions import IfCondition
from launch.substitutions import PythonExpression


@launch_this
def a_relic_of_the_past(
    turtlesim_ns: str = "turtlesim1", 
    use_provided_red: bool = False, 
    new_background_r: int = 200,
    kill_after: float = 10.0,
):
    """
    This example reimplements the `turtlesim example<https://docs.ros.org/en/jazzy/Tutorials/Intermediate/Launch/Using-Substitutions.html#substitutions-example-launch-file>`_ from the ROS2 documentation.

    When including ROS2 launch actions, better_launch creates a child process which will run the ROS2 `LaunchService` instance which will handle the passed actions asynchronously in the background. This is also true for including ROS2 launch files.

    Unfortunately, due to their ludicrous complexity, it is not feasible to digest and analyze what these actions are doing, especially when better_launch was written as an alternative. For this reason, anything started via the ROS2 launch system by better_launch will appear under a single 'LaunchService' node in the TUI.
    """
    bl = BetterLaunch()

    # If you really want to you can do this, but I will heavily frown on you
    bl.ros2_actions(
        Node(
            package='turtlesim',
            namespace=turtlesim_ns,
            executable='turtlesim_node',
            name='sim'
        ),
        ExecuteProcess(
            cmd=[[
                'ros2 service call ',
                turtlesim_ns,
                '/spawn ',
                'turtlesim/srv/Spawn ',
                '"{x: 2, y: 2, theta: 0.2}"'  # wtf is this?!
            ]],
            shell=True
        ),
        ExecuteProcess(
            cmd=[[
                'ros2 param set ',
                turtlesim_ns,
                '/sim background_r ',
                '120'
            ]],
            shell=True
        ),
        TimerAction(
            period=2.0,
            actions=[
                ExecuteProcess(
                    condition=IfCondition(
                        PythonExpression([
                            str(new_background_r),  # yes, this is necessary
                            ' == 200',
                            ' and ',
                            str(use_provided_red)
                        ])
                    ),
                    cmd=[[
                        'ros2 param set ',
                        turtlesim_ns,
                        '/sim background_r ',
                        str(new_background_r)
                    ]],
                    shell=True
                )
            ]
        ),
    )

    # When running without the TUI, the launch function will run on the main thread. In the TUI however, the launch function will be executed on a separate thread, so this will still be okay
    bl.logger.info(f"Waiting for {kill_after}s before shutting down turtlesim")
    time.sleep(kill_after)

    # Let's tear down this mess. The next example will show how to do better
    bl.ros2_launch_service().shutdown("We regret everything")
