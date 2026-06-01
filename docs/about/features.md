# :puzzle_piece: Okay, what can I do with it?
Everything! *better_launch*  can do everything ROS2 launch can do and some more. It's also faster, more reliabel, and comes with complete [API documentation](../reference/better_launch/index.md) and many [examples](https://github.com/dfki-ric/better_launch/tree/main/examples).

- create *nodes*, *composers*, *components*, *namespaces*, etc.
- create *subscribers*, *publishers*, *services*, etc. on the fly
- *predictable execution* allows you to interact with nodes right after starting them
- include other *better_launch launchfiles*
- include *and be included* from regular ROS2 launchfiles
- manage *lifecycle stages*
- *remap topics* using simple dicts
- launch arguments *passed directly* to your function
- easily *locate files* and load configs
- manage *nodes from other launch files*
- manage your node using a nice [terminal UI](../howto/tui.md) reminiscent of [rosmon](https://github.com/xqms/rosmon)
- write [TOML launchfiles](../howto/toml.md) with *ROS1-style substitutions*
- all of this and more with as few as *only 2 imports*

![TUI](../assets/images/tui_small1.png)

For a quick comparison, bravely unfold the sections below:

??? failure "ROS2"

    ```python
    # Taken from https://docs.ros.org/en/jazzy/Tutorials/Intermediate/Launch/Using-Substitutions.html
    from launch_ros.actions import Node

    from launch import LaunchDescription
    from launch.actions import DeclareLaunchArgument, ExecuteProcess, TimerAction
    from launch.conditions import IfCondition
    from launch.substitutions import LaunchConfiguration, PythonExpression


    def generate_launch_description():
        turtlesim_ns = LaunchConfiguration('turtlesim_ns')
        use_provided_red = LaunchConfiguration('use_provided_red')
        new_background_r = LaunchConfiguration('new_background_r')

        turtlesim_ns_launch_arg = DeclareLaunchArgument(
            'turtlesim_ns',
            default_value='turtlesim1'
        )
        use_provided_red_launch_arg = DeclareLaunchArgument(
            'use_provided_red',
            default_value='False'
        )
        new_background_r_launch_arg = DeclareLaunchArgument(
            'new_background_r',
            default_value='200'
        )

        turtlesim_node = Node(
            package='turtlesim',
            namespace=turtlesim_ns,
            executable='turtlesim_node',
            name='sim'
        )
        spawn_turtle = ExecuteProcess(
            cmd=[[
                'ros2 service call ',
                turtlesim_ns,
                '/spawn ',
                'turtlesim/srv/Spawn ',
                '"{x: 2, y: 2, theta: 0.2}"'
            ]],
            shell=True
        )
        change_background_r = ExecuteProcess(
            cmd=[[
                'ros2 param set ',
                turtlesim_ns,
                '/sim background_r ',
                '120'
            ]],
            shell=True
        )
        change_background_r_conditioned = ExecuteProcess(
            condition=IfCondition(
                PythonExpression([
                    new_background_r,
                    ' == 200',
                    ' and ',
                    use_provided_red
                ])
            ),
            cmd=[[
                'ros2 param set ',
                turtlesim_ns,
                '/sim background_r ',
                new_background_r
            ]],
            shell=True
        )

        return LaunchDescription([
            turtlesim_ns_launch_arg,
            use_provided_red_launch_arg,
            new_background_r_launch_arg,
            turtlesim_node,
            spawn_turtle,
            change_background_r,
            TimerAction(
                period=2.0,
                actions=[change_background_r_conditioned],
            )
        ])
    ```
    

??? success "better_launch (python)"

    ```python
    from better_launch import BetterLaunch, launch_this
    from rclpy import Timer

    @launch_this
    def my_start(
        # Launch arguments in function signature
        turtlesim_ns: str = "turtlesim1", 
        use_provided_red: bool = False, 
        new_background_r: int = 200,
    ):
        bl = BetterLaunch()

        # Pythonic AF
        with bl.group(turtlesim_ns):
            turtle_node = bl.node(
                package="turtlesim",
                executable="turtlesim_node",
                name="sim",
                # Pass parameters directly 
                params={"background_r": 120}
            )

            # Convenient API for common tasks
            bl.call_service(
                topic=f"/{turtlesim_ns}/spawn",
                service_type="turtlesim/srv/Spawn",
                # No weird types like passing dicts as strings
                request_args={"x": 2.0, "y": 2.0, "theta": 0.2},
            )

            if new_background_r == 200 and use_provided_red:
                turtle_node.is_ros2_connected(timeout=None)
                turtle_node.set_live_params({"background_r": new_background_r})
    ```

