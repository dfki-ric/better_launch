"""Additional convenience methods that aren't general enough to be added to the main namespace."""

__all__ = [
    "rviz",
    "read_robot_description",
    "joint_state_publisher",
    "robot_state_publisher",
    "static_transform_publisher",
    "spawn_controller_manager",
    "spawn_controller",
    "record_topics",
    "record_topics_from_file",
]


from typing import Sequence, Any, Literal, Callable
import os
import subprocess
import json
import yaml
import tempfile

from better_launch import BetterLaunch
from better_launch.elements import Node


def rviz(
    package: str = None,
    configfile: str = None,
    subdir: str = None,
    *,
    extra_args: list[str] = None,
) -> Node:
    """Runs RViz2 with the given config file and optional warning level suppression.

    Parameters
    ----------
    package : str, optional
        Path to locate the config file in (if one is specified).
    configfile : str, optional
        Path to the RViz2 configuration file which will be resolved by [BetterLaunch.find][]. Otherwise RViz2 will run with the default config.
    subdir : str, optional
        A path fragment the config file must be located in.
    extra_args : list[str], optional
        Additional args to pass to the RViz2 executable.

    Returns
    -------
    Node
        The spawned node instance.
    """
    bl = BetterLaunch.instance()

    args = []
    if configfile:
        configfile = bl.find(package, configfile, subdir)
        args += ["-d", configfile]

    if extra_args:
        args.extend(extra_args)

    # rviz2 doesn't support the --log-level argument nodes usually accept
    return bl.node(
        "rviz2", "rviz2", "rviz2", anonymous=True, cmd_args=args, log_level=None
    )


def read_robot_description(
    package: str,
    description_file: str,
    subdir: str = None,
    *,
    xacro_args: list[str] = None,
) -> str | None:
    """Returns the contents of a robot description after a potential xacro parse.

    The file is resolved using [BetterLaunch.find][]. If the description file ends with `.urdf` and `xacro_args` is not provided, it reads the URDF file directly. Otherwise it runs `xacro` to generate the URDF from a `.xacro` file.

    Parameters
    ----------
    package : str
        The package where the robot description file is located. May be `None` to use this launch file's package (see [BetterLaunch.find][]).
    description_file : str
        The name of the robot description file (URDF or XACRO).
    subdir : str, optional
        A path fragment the description file must be located in.
    xacro_args : list of str, optional
        Additional arguments to pass to `xacro` when processing `.xacro` files.

    Returns
    -------
    str | None
        The parsed URDF XML as a string if successful, `None` otherwise.

    Raises
    ------
    ValueError
        If the xacro command encountered an error while processing the file.
    """
    bl = BetterLaunch.instance()

    filepath = bl.find(package, description_file, subdir)

    if not filepath.endswith("xacro") and xacro_args is None:
        with open(filepath) as f:
            return f.read()

    args = [filepath]
    if xacro_args:
        args.extend(xacro_args)

    try:
        return bl.exec(["xacro", *args])
    except subprocess.CalledProcessError as e:
        raise ValueError(f"Xacro failed ({e.returncode}): {e.output}") from e


# Don't think this is useful enough to be part of the public api
def _resolve_robot_description(
    source: str,
    as_topic: bool,
    topic: str = "/robot_description",
    *,
    xacro_args: list[str] = None,
) -> str:
    """Prepares a robot description for passing to another node.

    If `source` points to a file, read it. Then, if `as_topic` is True and `source` looks like xml, create a publisher on `topic` and publish the contents.

    Note that if a topic or anything else that does not match the above criteria is passed in, it will be returned verbatim.

    Parameters
    ----------
    source : str
        A robot description topic, file path, or contents.
    as_topic : bool
        If True and either a file path or xml contents were passed, publish the robot description on the specified topic.
    topic : str, optional
        Where to publish the robot description contents.
    xacro_args : list[str], optional
        Xacro args to be passed to `read_robot_description` if the source is a xacro file.

    Returns
    -------
    str
        The contents of the robot description if a file was loaded, otherwise `source` as is.
    """
    from std_msgs.msg import String

    bl = BetterLaunch()

    if os.path.isfile(source):
        source = read_robot_description(None, source, xacro_args=xacro_args)

    if as_topic and source.lstrip().startswith("<"):
        source = source.strip()
        pub = bl.publisher(
            topic,
            String,
            bl.qos_profile(durability="transient_local"),
        )
        pub.publish(String(data=source))

    return source


def joint_state_publisher(
    use_gui: bool = False, node_name: str = None, **kwargs
) -> Node:
    """Starts a `joint_state_publisher` or `joint_state_publisher_gui` node.

    Parameters
    ----------
    use_gui : bool, optional
        Whether to use the GUI version of the `joint_state_publisher`.
    node_name : str, optional
        The name of the node. If not provided the name of the executable will be used. Will be anonymized unless `anonymous=False` is passed.
    **kwargs : dict, optional
        Additional arguments to pass to the node (e.g. name, remaps, params, etc.). See [BetterLaunch.node][].

    Returns
    -------
    Node
        The spawned node instance.
    """
    bl = BetterLaunch.instance()

    kwargs.setdefault("anonymous", True)

    if use_gui:
        return bl.node(
            "joint_state_publisher_gui",
            "joint_state_publisher_gui",
            node_name or "joint_state_publisher_gui",
            **kwargs,
        )
    else:
        return bl.node(
            "joint_state_publisher",
            "joint_state_publisher",
            node_name or "joint_state_publisher",
            **kwargs,
        )


def robot_state_publisher(
    robot_description: str = None,
    *,
    node_name: str = None,
    pass_by_topic: bool = False,
    description_topic: str = "/robot_description",
    xacro_args: list[str] = None,
    **kwargs,
) -> Node:
    """Start a Robot State Publisher node from a robot description. 

    Parameters
    ----------
    robot_description : str, optional
        Robot description the state publisher will use. This can be a urdf/xacro file path (e.g. from [BetterLaunch.find][]), a topic, or an xml string as returned by [read_robot_description][]. See also `pass_by_topic`. If not set it will be read from `/robot_description` (subject to remaps).
    node_name : str, optional
        The name of the node. If not provided the name of the executable will be used. Will be anonymized unless `anonymous=False` is passed.
    xacro_args : list of str, optional
        Additional arguments to pass to the Xacro processor when a `.xacro` file was passed.
    pass_by_topic : bool, optional
        If True and the value provided for `robot_description` is either a file or xml string, the description will be passed to the controller manager via a topic rather than a ROS parameter. On ROS versions before lyrical this feature is disabled.
    description_topic : str, optional
        The topic under which the robot description will be published if `pass_by_topic` is True.
    **kwargs : dict, optional
        Additional arguments for the node, such as remappings or parameters.

    Returns
    -------
    Node
        The spawned node instance.
    """
    bl = BetterLaunch.instance()

    if bl.ros_distro_key() < "l":
        pass_by_topic = False

    kwargs.setdefault("anonymous", True)
    params = kwargs.pop("params", {})
    remaps = kwargs.pop("remaps", {})

    if not robot_description:
        robot_description = "/robot_description"

    robot_description = _resolve_robot_description(
        robot_description,
        pass_by_topic,
        description_topic,
        xacro_args=xacro_args,
    )

    if not robot_description.lstrip().startswith("<"):
        # Input arg was not a file or xml content string, assume it's a topic
        if bl.ros_distro_key() < "l":
            # Before lyrical we need to read the topic and pass it as a parameter
            rd_msg = bl.receive_message(
                robot_description, "std_msgs/msg/String", None, timeout=1.0
            )
            if not rd_msg:
                raise ValueError(
                    f"Failed to read robot description from {robot_description}"
                )

            robot_description = rd_msg.data
            params["robot_description"] = robot_description
        else:
            # On lyrical and higher we can simply forward the assumed topic string
            if remaps.get("robot_description") not in (None, description_topic):
                raise ValueError(
                    "Cannot remap robot_description to a different topic when pass_by_topic is True, modify description_topic instead"
                )

            remaps["robot_description"] = robot_description
            params["use_robot_description_topic"] = True
    elif pass_by_topic:
        # We managed to read the description contents and want to pass them by topic
        if remaps.get("robot_description") not in (None, description_topic):
            raise ValueError(
                "Cannot remap robot_description to a different topic when pass_by_topic is True, modify description_topic instead"
            )

        remaps["robot_description"] = description_topic
        params["use_robot_description_topic"] = True
    else:
        # We received description contents that should be passed by parameter instead of topic
        params["robot_description"] = robot_description

    node = bl.node(
        "robot_state_publisher",
        "robot_state_publisher",
        node_name,
        params=params,
        remaps=remaps,
        **kwargs,
    )

    return node


def static_transform_publisher(
    parent_frame: str,
    child_frame: str,
    pos: Sequence[float] = None,
    rot: Sequence[float] = None,
) -> Node:
    """Publish a static transform between two frames.

    Parameters
    ----------
    parent_frame : str
        The parent or source frame.
    child_frame : str
        The child or target frame.
    pos : Sequence[float], optional
        The xyz-translation from parent to child frame. You may also pass a sequence of 6 or 7 floats in order to specify a full pose. In this case, `rot` will be ignored.
    rot : Sequence[float], optional
        The rotation between the parent and child frame. If length is 3, the values are interpreted as roll-pitch-yaw euler angles. If length is 4, an xyzw-quaternion is assumed.

    Returns
    -------
    Node
        The node running the publisher process.

    Raises
    ------
    ValueError
        If pos or rot have the wrong length.
    """
    args = ["--frame-id", parent_frame, "--child-frame-id", child_frame]

    # Position may also hold the pose
    if pos is not None:
        args.extend(["--x", pos[0], "--y", pos[1], "--z", pos[2]])
        if len(pos) == 3:
            pass
        elif len(pos) == 4 and pos[3] == 1.0:
            # Homogenous translation vector, it's fine
            pass
        elif len(pos) in (6, 7):
            rot = pos[3:]
        else:
            raise ValueError("Position has dubious length %d", len(pos))

    if rot is not None:
        if len(rot) == 3:
            args.extend(["--roll", rot[0], "--pitch", rot[1], "--yaw", rot[2]])
        elif len(rot) == 4:
            args.extend(
                ["--qx", rot[0], "--qy", rot[1], "--qz", rot[2], "--qw", rot[3]]
            )
        else:
            raise ValueError("Rotation has dubious length %d", len(rot))

    bl = BetterLaunch.instance()
    return bl.node(
        "tf2_ros",
        "static_transform_publisher",
        "gazebo_world_tf",
        cmd_args=args,
        log_level=None,
    )


def spawn_controller_manager(
    param_files: str | list[str] = None,
    robot_description: str = None,
    *,
    remaps: dict[str, str] = None,
    params: dict[str, Any] = None,
    cmd_args: list[str] = None,
    name: str = "controller_manager",
    pass_by_topic: bool = True,
    description_topic: str = "/robot_description",
    xacro_args: list[str] = None,
) -> Node:
    """Spawn a new controller manager.

    Parameters
    ----------
    param_files : str | list[str], optional
        One or more config files to be read by the controller manager. These will also be passed on to any controllers loaded and are often the only way to provide them with namespaced parameters.
    robot_description : str, optional
        Robot description to pass to the controller. This can be a urdf/xacro file path (e.g. from [BetterLaunch.find][]), a topic, or an xml string as returned by [read_robot_description][]. See also `pass_by_topic`. If not set the manager's default is used (`~/robot_description`, subject to remaps).
    remaps : dict[str, str], optional
        Topic remaps for the controller manager, e.g. for the `~/robot_description` topic it usually subscribes to.
    params : str | dict[str, Any], optional
        The controller manager config to use (typically named `controller.yaml`). If a string is passed it is considered as a path and loaded via [BetterLaunch.load_params][].
    cmd_args: list[str], optional
        Additional CLI arguments to pass to the spawner command (e.g. `--load-only`).
    name : str, optional
    pass_by_topic : bool, optional
        If True and the value provided for `robot_description` is either a file or xml string, the description will be passed to the controller manager via a topic rather than a ROS parameter. Automatically enabled on jazzy and newer, where passing by parameter is no longer supported.
    description_topic : str, optional
        Where to publish the robot description if `pass_by_topic` is True.
    xacro_args : list[str], optional
        Additional arguments to pass to the Xacro processor when a `.xacro` robot description file was passed.

        The name the controller manager node should use. The rename is qualified and so won't affect controllers spawned later (see [this document](https://control.ros.org/humble/doc/ros2_control/controller_manager/doc/userdoc.html#using-the-controller-manager-in-a-process) for details). Note however that many nodes and CLI programs (e.g. `ros2 control`) expect the manager to be named `controller_manager` and won't work properly otherwise.

    Returns
    -------
    Node
        The node running the controller manager process.
    """
    bl = BetterLaunch.instance()

    # In ROS2 there isn't a central parameter server anymore. However, each ROS2 process stores
    # context object with all ros args passed to it. If the process creates new nodes their
    # startup arguments are populated from this context object. This way the controller manager
    # can store parameters for other controllers even if they are only spawned later.
    # See this very helpful summary for details:
    # https://github.com/ros-controls/ros2_control/issues/335

    if params is None:
        params = {}

    if robot_description:
        # Passing by parameter is not supported in jazzy and onwwards
        if bl.ros_distro_key() >= "j":
            pass_by_topic = True

        robot_description = _resolve_robot_description(
            robot_description,
            pass_by_topic,
            description_topic,
            xacro_args=xacro_args,
        )

        if pass_by_topic:
            if remaps is None:
                remaps = {}
            elif remaps.get("robot_description") not in (None, description_topic):
                raise ValueError(
                    "Cannot remap robot_description to a different topic when pass_by_topic is True, modify description_topic instead"
                )

            remaps["robot_description"] = description_topic
        else:
            # Pass it as a parameter
            params["robot_description"] = robot_description

    else:
        if bl.ros_distro_key() < "j":
            bl.logger.warning(
                "Note that in distros before Jazzy the controller_manager is subscribing to '~/robot_description' by default!"
            )

    return bl.node(
        package="controller_manager",
        executable="ros2_control_node",
        name=name,
        remaps=remaps,
        params=params,
        param_files=param_files,
        cmd_args=cmd_args,
        # Prevent renaming nodes spawned by the manager
        # See https://control.ros.org/humble/doc/ros2_control/controller_manager/doc/userdoc.html#using-the-controller-manager-in-a-process
        remap_qualifier="controller_manager",
    )


def spawn_controller(
    controller: str,
    params: str | list[str] | dict[str, Any] = None,
    *,
    remaps: dict[str, str] = None,
    cmd_args: list[str] = None,
    manager: str = "controller_manager",
) -> None:  # TODO find a way to return an interactable object
    """Spawn the specified controller.

    Note that right now there is no way to directly interact with the loaded controller's node due to the limited API ROS2 provides. I will find a way...

    Parameters
    ----------
    controller : str
        The controller to spwawn.
    params : str | list[str] | dict[str, Any], optional
        Additional parameters for the controller node. Can be a path to a ROS2 config, a list of paths, or a dict with the actual key-value pairs. In versions of ROS before Jazzy the params will be serialized into a temporary yaml file.
    remaps : dict[str, str], optional
        Additional remaps specific to the controller. These will be qualified with the controller's name to avoid conflicts.
    cmd_args: list[str], optional
        Additional CLI arguments to pass to the spawner command (e.g. `--load-only`).
    manager : str, optional
        The name of the controller_manager node.
    """
    bl = BetterLaunch.instance()
    process_args = [controller, "--controller-manager", manager]

    if cmd_args:
        process_args.extend(cmd_args)

    if isinstance(params, str):
        params = bl.load_params(None, params)

    if params:
        # Passing controller params directly is only supported in Jazzy and newer, so we
        # write them to a yaml instead, then pass them as a param-file
        if isinstance(params, dict) and bl.ros_distro_key() < "j":
            data = yaml.serialize(params).splitlines()

            tmp = tempfile.NamedTemporaryFile("w+", suffix=".yaml")
            bl.logger.warning(
                f"ROS2 {bl.ros_distro()} does not support passing params to controllers directly, serializing to {tmp.name} instead"
            )
            tmp.writelines(data)
            bl.add_shutdown_callback(tmp.close)

            params = tmp.name

        # Decide how to pass the params to the controller
        if isinstance(params, dict):
            manager_node = bl.query_node(manager, include_foreign=True)

            if not manager_node:
                raise ValueError(f'Could not find controller manager "{manager}"')

            # In theory we could pass --controller-ros-args to the spawner and let the spawner
            # handle these, but it unfortunately does some very naive string splitting which
            # messes up more complex arguments containing e.g. lists.
            manager_node.set_live_params(
                {
                    f"{controller}.node_options_args": [
                        f"{key}:={json.dumps(val)}" for key, val in params.items()
                    ]
                }
            )
        elif isinstance(params, str):
            # Usually we'd load the parameters here and pass them to the controller manager,
            # but this functionality only exists from jazzy onwards
            process_args.extend(["--param-file", params])
        elif isinstance(params, list):
            for path in params:
                process_args.extend(["--param-file", path])
        else:
            raise ValueError(f"Controller params of type {type(params)} not supported")

    if remaps:
        if bl.ros_distro_key() < "j":
            raise ValueError(
                "Passing controller params directly is only supported in Jazzy and newer"
            )

        for key, value in remaps.items():
            # Qualify remaps to avoid accidental remaps for other controllers
            process_args.extend(
                ["--controller-ros-args", f"-r {controller}:{key}:={value}"]
            )

    # This is NOT a node! Could also use the spawner python implementation directly, but that
    # would just introduce another dependency with little benefit.
    spawner = bl.find("controller_manager", "spawner")
    bl.exec(["python3", spawner] + process_args)


def record_topics(
    topics: list[str] = None,
    predicate: Callable[[str], bool] = None,
    *,
    bagdir: str = None,
    max_bag_duration: int = 0,
    max_bag_size: float = 0.0,
    recordings: int = 1,
    wait: bool = True,
    format: Literal["mcap", "sqlite3"] = "mcap",
    extra_args: list[str] = None,
) -> None | Node:
    """Record a rosbag.

    If topics is empty or not specified all currently published topics are used. The list of topics will be filtered by the predicate if provided.

    Parameters
    ----------
    topics : list[str], optional
        The ROS topics to record. If not specified all currently known topics will be used instead.
    predicate : Callable[[str], bool], optional
        A function to decide which topics to record. I suggest to use fnmatch for simple wildcards.
    bagdir : str, optional
        Where to record the bagfile. If not specified it will use the rosbag default (a timestamped folder in the currend working directory).
    max_bag_duration : int, optional
        Start recording a new bagfile after recording for X seconds.
    max_bag_size : float, optional
        Start recording a new bagfile after recording X MB.
    recordings : int, optional
        Make this many recordings each with the set maximum bag duration/size. Continue until interrupted if <= 0. Multiple recordings can only be done when `wait` is True.
    wait : bool, optional
        If True, wait for the recording to finish before returning. Otherwise the process will be wrapped in a [elements.Node][] object and returned. Must be True if `recordings` is != 1.
    format : Literal["mcap", "sqlite3"], optional
        Rosbag recording format, should be mcap or sqlite3.
    extra_args : Iterable[str], optional
        Additional arguments that will be passed to rosbag.

    Returns
    -------
    None | Node
        Nothing if wait is True, otherwise a [elements.Node][] object wrapping the recording process.
    """
    if recordings != 1 and not wait:
        raise ValueError("For multiple recordings wait must be True")

    bl = BetterLaunch()

    if not topics:
        topics = [t for t, _ in bl.shared_node.get_topic_names_and_types()]

    cmd = [
        "ros2",
        "bag",
        "record",
        "--storage",
        format,
        "--max-bag-duration",
        int(max_bag_duration),
        "--max-bag-size",
        int(max_bag_size * 1024 * 1024),
    ]

    if bagdir:
        cmd.extend(["-o", bagdir])

    if extra_args:
        cmd.extend(extra_args)

    if predicate:
        topics = list(filter(predicate, topics))

    if not topics:
        raise ValueError("No topics left to record")

    cmd.extend(topics)
    cmd = [str(x) for x in cmd]
    count = 0

    while True and not bl.is_shutdown:
        bl.logger.critical(f"\n===== RECORDING {count + 1} =====\n")
        if wait:
            bl.exec(cmd)
            count += 1
            if recordings > 0 and count >= recordings:
                break
        else:
            return bl.process(cmd)


def record_topics_from_file(
    topic_file: str,
    predicate: Callable[[str], bool] = None,
    *,
    bagdir: str = None,
    max_bag_duration: int = 0,
    max_bag_size: float = 0,
    recordings: int = 1,
    wait: bool = True,
    format: Literal["mcap", "sqlite3"] = "mcap",
    extra_args: list[str] = None,
) -> None | Node:
    """Record a rosbag.

    Reads topics to record from a text-file. Empty lines and lines starting with "#" will be ignored.

    Parameters
    ----------
    topic_file : str
        The file to read the topic list from.
    predicate : Callable[[str], bool], optional
        A function to decide which topics to record. I suggest to use fnmatch for simple wildcards.
    bagdir : str, optional
        Where to record the bagfile. If not specified it will use the rosbag default (a timestamped folder in the currend working directory).
    topic_file : str, optional
        Text file with topics to record. Lines starting with "#" will be ignored.
    max_bag_duration : int, optional
        Start recording a new bagfile after recording for X seconds.
    max_bag_size : float, optional
        Start recording a new bagfile after recording X MB.
    recordings : int, optional
        Make this many recordings each with the set maximum bag duration/size. Continue until interrupted if <= 0. Multiple recordings can only be done when `wait` is True.
    wait : bool, optional
        If True, wait for the recording to finish before returning. Otherwise the process will be wrapped in a [elements.Node][] object and returned. Must be True if `recordings` is != 1.
    format : Literal["mcap", "sqlite3"], optional
        Rosbag recording format, should be mcap or sqlite3.
    extra_args : Iterable[str], optional
        Additional arguments that will be passed to rosbag.

    Returns
    -------
    None | Node
        Nothing if wait is True, otherwise a [elements.Node][] object wrapping the recording process.
    """
    with open(topic_file) as f:
        lines = f.readlines()

    topics = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        topics.append(line)

    return record_topics(
        topics,
        predicate=predicate,
        bagdir=bagdir,
        max_bag_duration=max_bag_duration,
        max_bag_size=max_bag_size,
        recordings=recordings,
        wait=wait,
        format=format,
        extra_args=extra_args,
    )
