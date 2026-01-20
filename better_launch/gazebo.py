"""Additional functions for working with Gazebo, taking inspiration from simple_launch."""

__all__ = [
    "get_gazebo_version",
    "gazebo_launch",
    "save_world",
    "spawn_model",
    "spawn_topic_bridge",
    "spawn_image_bridge",
    "spawn_world_transform",
    "get_gazebo_axes_args",
    "GazeboBridge",
]


from typing import Any, Literal, Union
import os
import re
import shutil

from ament_index_python.packages import (
    get_package_share_directory,
    PackageNotFoundError,
)

from better_launch import BetterLaunch
from better_launch.elements import Node
from .convenience import static_transform_publisher


_gazebo_exec = None
_active_world = None


def get_gazebo_version() -> str:
    """For a short time, Gazebo rebranded to "Ignition" before returning to Gazebo again. This function returns the associated prefix.

    Returns
    -------
    str
        The prefix indicating the type of Gazebo: "ign" for Ignition Gazebo or "gz" for Gazebo Classic.
    """

    for var in ["IGN_VERSION", "IGNITION_VERSION", "GZ_VERSION"]:
        version = os.environ.get(var, None)
        if version:
            return "ign" if version == "fortress" else "gz"

    try:
        get_package_share_directory("ros_gz_sim")
        return "gz"
    except PackageNotFoundError:
        return "ign"


def get_gazebo_exec() -> str:
    """Locates the gazebo executable.

    Returns
    -------
    str
        Full path to the gazebo executable.

    Raises
    ------
    ValueError
        If the executable cannot be located.
    """
    global _gazebo_exec
    
    if not _gazebo_exec:
        # On some systems ros_gz_sim was installed, but the executable was still ign
        _gazebo_exec = shutil.which("gz")

        if not _gazebo_exec:
            _gazebo_exec = shutil.which("ign")

        if not _gazebo_exec:
            raise ValueError("Could not locate gazebo executable")

    return _gazebo_exec


def gazebo_launch(
    package: str,
    world_file: str,
    gz_args: list[str] = None,
    world_save_file: str = None,
    save_after: float = 10.0,
) -> None:
    """Starts a Gazebo simulation with the specified world. If `world_save_file` is specified, the world will be saved as an SDF to that file after `save_after` seconds, including base world and spawned entities.

    Parameters
    ----------
    package : str,
        A package to locate the world_file in. May be `None` (see :py:meth:`BetterLaunch.find`).
    world_file : str
        Path to the primary world file for the simulation.
    gz_args : _type_, optional
        Optional arguments to pass to the Gazebo simulator.
    world_save_file : _type_, optional
        Path where the resulting SDF should be saved.
    save_after : float, optional
        Time in seconds after which the world SDF should be saved.
    """
    bl = BetterLaunch.instance()

    world_file = bl.find(package, world_file)
    if not os.path.exists(world_file):
        raise ValueError("Could not find world file")

    full_args = [world_file]
    if gz_args:
        full_args += gz_args

    full_args = " ".join(full_args)

    if get_gazebo_version() == "gz":
        launch_file = bl.find("ros_gz_sim", "gz_sim.launch.py")
        launch_arguments = {"gz_args": full_args}
    else:
        launch_file = bl.find("ros_ign_gazebo", "ign_gazebo.launch.py")
        launch_arguments = {"ign_args": full_args}

    # TODO It would be nice to avoid this include and launch gazebo without relying on an external
    # launch file. However, the launch file does quite a bit, searching for packages that provide
    # gazebo plugins and models
    bl.include(None, launch_file, **launch_arguments)

    if world_save_file:
        save_world(world_save_file, save_after)


def save_world(filepath: str, after: float = 5.0) -> None:
    """Saves the current gazebo world to a file. Resolves any spawned URDF through their description parameter and converts to SDF.

    Parameters
    ----------
    filepath : str
        Path to the file to save the gazebo world to.
    after : float, optional
        How long to wait before saving.
    """
    bl = BetterLaunch.instance()

    def save():
        bl.node(
            package="better_launch",
            executable="generate_gz_world",
            params={"output_path": filepath},
        )

    if after > 0.0:
        bl.run_later(after, save)
    else:
        save()


def get_active_world_name(force_query: bool = False) -> str:
    """Return the name of the currently loaded world. If it was not loaded from better_launch, Gazebo will be asked directly.

    Parameters
    ----------
    force_query : bool, optional
        If True, don't use the cached value.

    Returns
    -------
    str
        The name of a Gazebo world.

    Raises
    ------
    ValueError
        If querying Gazebo for the world name failed.
    """
    global _active_world

    if _active_world and not force_query:
        return _active_world

    try:
        output = BetterLaunch.exec([get_gazebo_exec(), "model", "--list"])
    except Exception as e:
        raise ValueError(f"Failed to list loaded Gazebo models: {e}")

    if not output or "timed out" in output:
        raise ValueError("No loaded Gazebo models or request timed out")

    world_name = output.replace("]", "[").split("[")[1]

    if not world_name:
        raise ValueError(
            f"Gazebo did not return a parseable world name (output was '{output}')"
        )

    _active_world = world_name
    return _active_world


def get_model_prefix(model: str) -> str:
    """
    Construct the Gazebo prefix string for the given model name.

    Parameters
    ----------
    model : str
        The name of the model.

    Returns
    -------
    str
        A string representing the model's prefix in the Gazebo world.
    """
    return f"/world/{get_active_world_name()}/model/{model}"


def get_model_topic(model: str, topic: str) -> str:
    """
    Constructs a string representing the model topic in Gazebo.

    Parameters
    ----------
    model : str
        The model name.
    topic : str
        The topic name related to the model.

    Returns
    -------
    str
        The path of the given model's specified topic.
    """
    # TODO verify: simple_launch only returns f"/model/{model}/{topic}", but that seems wrong
    return f"{get_model_prefix(model)}/{topic}"


def get_gazebo_axes_args(
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    yaw: float = 0.0,
    pitch: float = 0.0,
    roll: float = 0.0,
) -> dict[str, float]:
    """Constructs a list of command-line arguments that can be used e.g. when spawning a new model.

    Parameters
    ----------
    x : float, optional
        translation x component
    y : float, optional
        translation y component
    z : float, optional
        translation z component
    yaw : float, optional
        rotation yaw component
    pitch : float, optional
        rotation pitch component
    roll : float, optional
        rotation roll component

    Returns
    -------
    dict[str, float]
        A dictionary containing the axes names and values. The axes names correspond to what Gazebo expects on the command line and so can be passed to e.g. :py:meth:`gazebo_spawn_model`.
    """
    return {
        "x": x,
        "y": y,
        "z": z,
        "Y": yaw,
        "P": pitch,
        "R": roll,
    }


def spawn_model(
    model_name: str,
    model: str,
    model_source: Literal["topic", "file", "string", "param", "auto"] = "auto",
    spawn_args: dict[str, Any] = None,
) -> Node:
    """
    Spawns a model into Gazebo under the given name from the specified topic or file.

    The `spawn_args` dictionary can include additional options, such as the initial pose of the model.

    Note that when spawning robot models this way, they typically also need a :py:meth:`convenience.joint_state_publisher`.

    Parameters
    ----------
    name : str
        The name of the model to spawn in the Gazebo environment.
    model : str
        The model to spawn. The contents of this string depend on the model_source, but should ultimately lead to a full XML description.
    model_source : str
        Where to read the model from. Auto will try to guess the source based on the content of `model`: does it look like XML, is it a file, is it an existing topic? Otherwise assume it's a ROS2 parameter.
    spawn_args : dict[str, Any], optional
        Additional arguments for spawning the model, such as pose and other options. See :py:meth:`get_gazebo_axes_args` for defining the model's orientation.

    Returns
    -------
    Node
        The spawned node instance.
    """
    bl = BetterLaunch.instance()

    if spawn_args is None:
        spawn_args = {}

    if model_source == "auto":
        if "<model" in model:
            model_source = "string"
        elif os.path.isfile(model):
            model_source = "file"
        elif model in {t[0] for t in bl.shared_node.get_topic_names_and_types()}:
            model_source = "topic"
        else:
            model_source = "param"

    cmd_args = ["-name", model_name, f"-{model_source}", model]

    for key, val in spawn_args.items():
        cmd_args.extend([f"-{key}", val])

    pkg = "ros_ign_gazebo" if get_gazebo_version() == "ign" else "ros_gz_sim"
    return bl.node(
        pkg, "create", f"spawn_{model_name}", anonymous=True, cmd_args=cmd_args
    )


def spawn_world_transform(gazebo_world_frame: str = None) -> Node:
    """
    Runs a static_transform_publisher to connect the ROS `world` frame and a Gazebo world frame, if the Gazebo world frame is specified and different from 'world'.

    Parameters
    ----------
    gazebo_world_frame : str, optional
        The name of the Gazebo world frame. If None, retrieves the default from :py:meth:`GazeboBridge.world`.

    Returns
    -------
    Node
        The spawned node instance.
    """
    if gazebo_world_frame is None:
        gazebo_world_frame = get_active_world_name()

    if gazebo_world_frame != "world":
        return static_transform_publisher("world", gazebo_world_frame)

    return None


def spawn_topic_bridge(
    *bridges: Union[str, "GazeboBridge"],
    node_name: str = "gz_bridge",
    remaps: dict[str, str] = None,
    cmd_args: list[str] = None,
    **kwargs,
) -> Node:
    """Start a Gazebo topic bridge to relay messages between ROS2 and Gazebo.

    Note that there is a separate function for bridging image topics more efficiently. See :py:meth:`spawn_image_bridge`.

    Parameters
    ----------
    bridges : list[str | GazeboBridge]
        Definitions of topic bridges. This can be either a typical string (`<topic>@<ros2_type><direction><gazebo_type>`) or a :py:class:`GazeboBridge` instance. Note that in order to bridge services you will have to specify them as strings for now. 
    node_name : str, optional
        The name of the bridge node.
    remaps : dict[str, str], optional
        Any topic remaps you wish to apply to the bridge.
    cmd_args : list[str], optional
        Additional command line arguments to the gazebo bridge executable.
    kwargs : dict[str, Any]
        Additional node arguments.

    Returns
    -------
    Node
        The node running the bridge process.
    """
    ros_gz = "ros_" + get_gazebo_version()
    bl = BetterLaunch.instance()

    all_remaps = {}

    bridges: list[str] = list(bridges)
    for i, b in enumerate(bridges):
        if not isinstance(b, GazeboBridge):
            b = GazeboBridge.from_string(b)
            bridges[i] = b

        if b.remaps:
            all_remaps.update(b.remaps)

    if remaps:
        all_remaps.update(remaps)

    args = [str(b) for b in bridges]
    if cmd_args:
        args.extend(cmd_args)

    return bl.node(
        f"{ros_gz}_bridge",
        "parameter_bridge",
        node_name,
        cmd_args=args,
        remaps=all_remaps,
        **kwargs
    )


def spawn_image_bridge(
    *bridges: Union[str, "GazeboBridge"],
    node_name: str = None,
    remaps: dict[str, str] = None,
    cmd_args: list[str] = None, 
    qos: str = None,
    **kwargs,
) -> Node:
    """Spawn a bridge to efficiently relay images from Gazebo to ROS2 (one direction only).

    Parameters
    ----------
    bridges : list[str | GazeboBridge]
        The image topics to bridge. These can be specified as either Gazebo bridge definitions, :py:class:`GazeboBridge` instances. Also accepts regular topics, in which case the type is assumed to be `sensor_msgs/Image`.
    node_name : str, optional
        The name of the node running the bridge.
    remaps : dict[str, str], optional
        How topics should be remapped in ROS2.
    cmd_args : list[str], optional
        Additional commandline arguments to the bridge executable.
    qos : str, optional
        The `ROS2 quality of service <https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Quality-of-Service-Settings.html>`_ definition to use. Note that this is not supported in all versions of ros-gz-image and may cause the bridge to terminate.
    kwargs : dict[str, Any]
        Additional node arguments.
    
    Returns
    -------
    Node
        The node running the bridge process.

    Raises
    ------
    ValueError
        If a topic is passed which is not an image topic.
    """
    all_remaps = {}

    bridges: list[GazeboBridge] = list(bridges)
    for i, b in enumerate(bridges):
        if not isinstance(b, GazeboBridge):
            try:
                b = GazeboBridge.from_string(b)
            except ValueError:
                b = GazeboBridge.from_string(f"{b}@sensor_msgs/msg/Image]gz.msgs.Image")
            
            bridges[i] = b

        if not b.is_image_bridge:
            raise ValueError(f"{b} is not an image bridge")

        if b.remaps:
            all_remaps.update(b.remaps)

    if remaps:
        all_remaps.update(remaps)

    for src in bridges:
        if src.topic in all_remaps:
            dst = all_remaps[src.topic]
            for ext in ("/compressed", "/compressedDepth", "/theora"):
                all_remaps.setdefault(src.topic + ext, dst + ext)

    args = [b.topic for b in bridges]
    
    if cmd_args:
        args.extend(cmd_args)
    
    if qos:
        args.extend(["--ros-args", f"qos:={qos}"])

    ros_gz = "ros_" + get_gazebo_version()
    bl = BetterLaunch.instance()

    return bl.node(
        f"{ros_gz}_image",
        "image_bridge",
        node_name,
        remaps=all_remaps,
        cmd_args=args,
        **kwargs
    )


class GazeboBridge:
    gazebo_message_types = {
        "actuator_msgs/msg/Actuators": "gz.msgs.Actuators",
        "builtin_interfaces/msg/Time": "gz.msgs.Time",
        "geometry_msgs/msg/Point": "gz.msgs.Vector3d",
        "geometry_msgs/msg/Pose": "gz.msgs.Pose",
        "geometry_msgs/msg/PoseArray": "gz.msgs.Pose_V",
        "geometry_msgs/msg/PoseStamped": "gz.msgs.Pose",
        "geometry_msgs/msg/PoseWithCovariance": "gz.msgs.PoseWithCovariance",
        "geometry_msgs/msg/PoseWithCovarianceStamped": "gz.msgs.PoseWithCovariance",
        "geometry_msgs/msg/Quaternion": "gz.msgs.Quaternion",
        "geometry_msgs/msg/Transform": "gz.msgs.Pose",
        "geometry_msgs/msg/TransformStamped": "gz.msgs.Pose",
        "geometry_msgs/msg/Twist": "gz.msgs.Twist",
        "geometry_msgs/msg/TwistStamped": "gz.msgs.Twist",
        "geometry_msgs/msg/TwistWithCovariance": "gz.msgs.TwistWithCovariance",
        "geometry_msgs/msg/TwistWithCovarianceStamped": "gz.msgs.TwistWithCovariance",
        "geometry_msgs/msg/Vector3": "gz.msgs.Vector3d",
        "geometry_msgs/msg/Wrench": "gz.msgs.Wrench",
        "geometry_msgs/msg/WrenchStamped": "gz.msgs.Wrench",
        "gps_msgs/msg/GPSFix": "gz.msgs.NavSat",
        "nav_msgs/msg/Odometry": "gz.msgs.OdometryWithCovariance",
        "rcl_interfaces/msg/ParameterValue": "gz.msgs.Any",
        "ros_gz_interfaces/msg/Altimeter": "gz.msgs.Altimeter",
        "ros_gz_interfaces/msg/Contact": "gz.msgs.Contact",
        "ros_gz_interfaces/msg/Contacts": "gz.msgs.Contacts",
        "ros_gz_interfaces/msg/Dataframe": "gz.msgs.Dataframe",
        "ros_gz_interfaces/msg/Entity": "gz.msgs.Entity",
        "ros_gz_interfaces/msg/Float32Array": "gz.msgs.Float_V",
        "ros_gz_interfaces/msg/GuiCamera": "gz.msgs.GUICamera",
        "ros_gz_interfaces/msg/JointWrench": "gz.msgs.JointWrench",
        "ros_gz_interfaces/msg/Light": "gz.msgs.Light",
        "ros_gz_interfaces/msg/ParamVec": "gz.msgs.Param",
        "ros_gz_interfaces/msg/SensorNoise": "gz.msgs.SensorNoise",
        "ros_gz_interfaces/msg/StringVec": "gz.msgs.StringMsg_V",
        "ros_gz_interfaces/msg/TrackVisual": "gz.msgs.TrackVisual",
        "ros_gz_interfaces/msg/VideoRecord": "gz.msgs.VideoRecord",
        "rosgraph_msgs/msg/Clock": "gz.msgs.Clock",
        "sensor_msgs/msg/BatteryState": "gz.msgs.BatteryState",
        "sensor_msgs/msg/CameraInfo": "gz.msgs.CameraInfo",
        "sensor_msgs/msg/FluidPressure": "gz.msgs.FluidPressure",
        "sensor_msgs/msg/Image": "gz.msgs.Image",
        "sensor_msgs/msg/Imu": "gz.msgs.IMU",
        "sensor_msgs/msg/JointState": "gz.msgs.Model",
        "sensor_msgs/msg/Joy": "gz.msgs.Joy",
        "sensor_msgs/msg/LaserScan": "gz.msgs.LaserScan",
        "sensor_msgs/msg/MagneticField": "gz.msgs.Magnetometer",
        "sensor_msgs/msg/NavSatFix": "gz.msgs.NavSat",
        "sensor_msgs/msg/PointCloud2": "gz.msgs.PointCloudPacked",
        "std_msgs/msg/Bool": "gz.msgs.Boolean",
        "std_msgs/msg/ColorRGBA": "gz.msgs.Color",
        "std_msgs/msg/Empty": "gz.msgs.Empty",
        "std_msgs/msg/Float32": "gz.msgs.Float",
        "std_msgs/msg/Float64": "gz.msgs.Double",
        "std_msgs/msg/Header": "gz.msgs.Header",
        "std_msgs/msg/Int32": "gz.msgs.Int32",
        "std_msgs/msg/String": "gz.msgs.StringMsg",
        "std_msgs/msg/UInt32": "gz.msgs.UInt32",
        "tf2_msgs/msg/TFMessage": "gz.msgs.Pose_V",
        "trajectory_msgs/msg/JointTrajectory": "gz.msgs.JointTrajectory",
        "vision_msgs/msg/Detection2D": "gz.msgs.AnnotatedAxisAligned2DBox",
        "vision_msgs/msg/Detection2DArray": "gz.msgs.AnnotatedAxisAligned2DBox_V",
    }

    @classmethod
    def from_string(cls, bridge: str, remaps: dict[str, str] = None) -> "GazeboBridge":
        """Extract the topic, ROS2 message type, direction, and gazebo message type from a bridge definition string.

        Parameters
        ----------
        bridge : str
            A bridge definition following the pattern `<topic>@<ros2_type><direction><gazebo_type>`.
        remaps : str, optional
            Topic remaps the bridge should use once it is started.

        Returns
        -------
        GazeboBridge
            An instance with the aforementionend parameters.

        Raises
        ------
        ValueError
            If the bridge string doesn't match the expected pattern.
        """
        m = re.match(r"(.+)@(.+)([\[\]@])(.+)", bridge)

        if not m:
            raise ValueError(bridge + " is not a valid bridge string")

        return GazeboBridge(m.group(1), m.group(2), m.group(3), m.group(4), remaps=remaps)

    @classmethod
    def clock_bridge(cls) -> "GazeboBridge":
        """
        Creates a GazeboBridge instance for bridging the /clock topic from Gazebo to ROS.

        Returns
        -------
        GazeboBridge
            An instance of the GazeboBridge for the clock topic.
        """
        return GazeboBridge("/clock", "rosgraph_msgs/msg/Clock", "gz2ros")

    @classmethod
    def joint_state_bridge(cls, model: str) -> "GazeboBridge":
        """
        Creates a GazeboBridge instance for the bridging the joint states of a given model to ROS.

        Parameters
        ----------
        model : str
            The model name to associate with the joint state topic.

        Returns
        -------
        GazeboBridge
            An instance of the GazeboBridge for the joint state topic.
        """
        topic = get_model_topic(model, "joint_state")
        return GazeboBridge(
            topic, "sensor_msgs/JointState", "gz2ros", remaps={topic: "joint_states"}
        )

    def __init__(
        self,
        topic: str,
        ros2_type: str = None,
        direction: Literal["ros2gz", "gz2ros", "bidirectional", "[", "]", "@"] = "bidirectional",
        gazebo_type: str = None,
        *,
        remaps: dict[str, str] = None,
    ):
        """Create a definition for a gazebo bridge. Convert to a string in order to get the canonical Gazebo bridge representation. To start a topic bridge see :py:meth:`spawn_topic_bridge`.

        Parameters
        ----------
        topic : str
            The ROS2 topic to bridge into Gazebo. Any remaps have to happen on the ROS2 side.
        ros2_type : str, optional
            The message type of the ROS2 topic. If not provided the type will be looked up in the currently published topics.
        direction : str, optional
            The direction in which messages will be passed,
        gazebo_type : str, optional
            The message type of the Gazebo topic. If not provided it will be looked up from the common :py:member:`gazebo_message_types`.
        remaps : dict[str, str], optional
            Additional topic remaps for the bridge node.

        Raises
        ------
        ValueError
            If an invalid direction is provided, or if the ROS2 message type was not specified and could not be looked up.
        """
        if direction == "ros2gz":
            direction = "]"
        elif direction == "gz2ros":
            direction = "["
        elif direction == "bidirectional":
            direction = "@"

        if not ros2_type:
            bl = BetterLaunch.instance()
            live_topics = bl.shared_node.get_topic_names_and_types()
            
            if topic not in live_topics:
                raise ValueError(f"Message type not specified and topic {topic} does not exist yet")
            
            ros2_type = live_topics[topic][0]

        if direction not in "[]@":
            raise ValueError(f"Invalid direction {direction}")

        if not gazebo_type:
            gazebo_type = self.gazebo_message_types[ros2_type]

        self.topic = topic
        self.ros2_type = ros2_type
        self.direction = direction
        self.gazebo_type = gazebo_type
        self.remaps = remaps
        self.is_image_bridge = ros2_type == "sensor_msgs/msg/Image"

    def __str__(self):
        return f"{self.topic}@{self.ros2_type}{self.direction}{self.gazebo_type}"

