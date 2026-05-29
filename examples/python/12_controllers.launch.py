#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this, convenience
from pprint import pprint


@launch_this
def parambolage():
    """This file demonstrates how to start a controller_manager and load a simple controller.

    Since ROS2 doesn't have a central parameter server, each process stores the parameters passed to it on their own. These will be used anytime a node is spawned within this process. This can lead to problems when using e.g. generic remaps on a process creating multiple nodes (e.g. composers, ros2 control manager, etc.), as all arguments (params, remaps, etc.) will apply to them - including names and namespaces.

    More details on this can be found here: https://control.ros.org/humble/doc/ros2_control/controller_manager/doc/userdoc.html#using-the-controller-manager-in-a-process.

    In order to avoid the aforementioned problems, params and remaps can be prefixed with a namespace or node name in order to make them more selective. This is done automatically when using `BetterLaunch.load_params`.
    """
    bl = BetterLaunch()

    # We could also pass the params file path to the node, but this way we have a bit
    # more control.
    params = bl.load_params("better_launch", "control_config.yaml")
    print("Loaded parameters:")
    pprint(params, indent=2)

    # We need a robot state publisher to load the URDF and publish it on [/robot_desciption]
    convenience.robot_state_publisher(
        bl.find(
            package="better_launch",
            filename="minimal_robot.urdf",
        ),
        node_name="robot_state_publisher",
        anonymous=False
    )

    remaps = {}
    if bl.ros_distro_key() < "j":
        # In versions before Jazzy the controller_manager was subscribing to something weird like 
        # /controller_manager/robot_description
        remaps["~/robot_description"] = "/robot_description"

    # NOTE we could use convenience.spawn_controller_manager, but this launch file also serves to
    # show how to load parameters and some more technical nuances
    bl.node(
        package="controller_manager",
        executable="ros2_control_node",
        name="controller_manager",
        params=params,
        remaps=remaps,
        # Qualify the name and namespace remaps with the ORIGINAL name of the manager. The original
        # name is passed to the node's implementation on construction and usually hardcoded.
        # See https://github.com/ros-controls/ros2_control/blob/6cbb5f0ff69c1abcab97dde4f99ccc84d0b3f5bb/controller_manager/src/ros2_control_node.cpp#L58
        remap_qualifier="controller_manager",
    )

    # Discover the manager node even if we didn't keep a reference to it
    manager = bl.query_node("controller_manager")
    print("Retrieving controller manager parameters")
    pprint(manager.get_live_params())

    convenience.spawn_controller("joint_state_broadcaster")
    print("Running ROS2 nodes:")
    pprint(bl.all_ros2_node_names())

    # TODO since the controller is spawned inside the controller manager's process, it is 
    # currently not possible to interact with it from better_launch. I will find a way...
    #controller = bl.query_node("/joint_state_broadcaster")
    #print(controller.get_live_params())

    ret = bl.call_service(
        "/joint_state_broadcaster/get_parameters",
        "rcl_interfaces/srv/GetParameters",
        request_args={"names": ["frame_id"]},
    )
    print(f"\n=> Is my frame awesome? {ret.values[0].string_value}\n")
