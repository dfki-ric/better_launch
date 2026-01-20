from typing import Any, Iterable
import signal
import time

import better_launch.ros.logging as roslog
from better_launch.utils.better_logging import LogSink, configure_logger
from better_launch.elements.lifecycle_manager import LifecycleManager


_node_counter = 0


class AbstractNode:
    def __init__(
        self,
        package: str,
        executable: str,
        name: str,
        namespace: str,
        remaps: dict[str, str] = None,
        params: str | dict[str, Any] = None,
        *,
        output: LogSink | Iterable[LogSink] | Iterable[str] | str = LogSink.SCREEN,
    ):
        """Base class for all node-like objects.

        Parameters
        ----------
        package : str
            The package this node can be found in.
        executable : str
            How the node can be executed. Not necessarily an executable file object.
        name : str
            This node's name. If it is a ROS node it should be how the node registers with ROS.
        namespace : str
            The node's namespace. Must be absolute, i.e. start with a '/'.
        remaps : dict[str, str], optional
            Topic remaps for this node.
        params : str | dict[str, Any], optional
            Node parameters. If a string is passed it will be lazy loaded with :py:meth:`BetterLaunch.find`.
        output : LogSink | Iterable[LogSink] | Iterable[str] | str, optional
            Determines if and where this node's output should be directed. Common choices are `screen` to print to terminal, `log` to write to a common log file, `own_log` to write to a node-specific log file, and `none` to not write any output anywhere. See :py:meth:`configure_logger` for details.

        Raises
        ------
        ValueError
            If the name is empty or the namespace is not absolute.
        """
        # Required so that other mixins are initialized properly
        super().__init__()

        if not name:
            raise ValueError("Name cannot be empty")

        if not namespace:
            namespace = "/"

        if not namespace.startswith("/"):
            raise ValueError("namespace must start with a '/'")

        global _node_counter
        self._node_id = _node_counter
        _node_counter += 1

        self._pkg = package
        self._exec = executable
        self._name = name
        self._namespace = namespace
        self._remaps = remaps or {}
        self._params = params or {}
        self._lifecycle_manager: LifecycleManager = None

        self.logger = roslog.get_logger(self.fullname)
        configure_logger(self.logger, output)

    @property
    def node_id(self) -> int:
        return self._node_id

    @property
    def package(self) -> str:
        """The package this node can be found in."""
        return self._pkg

    @property
    def executable(self) -> str:
        """How this node can be executed. This is not required to be an executable file. It's meaning depends on the node implementation."""
        return self._exec

    @property
    def name(self) -> str:
        """The name of this node. If this represents a ROS node this will also be the name by which it is known in ROS."""
        return self._name

    @property
    def namespace(self) -> str:
        """This node's namespace."""
        return self._namespace

    @property
    def fullname(self) -> str:
        """The concatenation of this node's namespace and name. Will always start with '/'."""
        ns = self.namespace.strip("/")
        if not ns:
            return "/" + self.name
        return "/" + ns + "/" + self.name

    @property
    def params(self) -> dict[str, Any]:
        """The ROS params that were passed to this node. If a string was passed it is assumed to be a filepath and will be loaded with :py:meth:`BetterLaunch.find`."""
        if isinstance(self._params, str):
            from better_launch import BetterLaunch

            bl = BetterLaunch.instance()
            if not bl:
                return self._params

            self._params = bl.load_params(None, self._params, qualifier=self)

        return self._params

    @property
    def remaps(self) -> dict[str, str]:
        """Any topic remaps that were passed to this node."""
        return self._remaps

    @property
    def is_running(self) -> bool:
        """True if the node is currently running."""
        raise NotImplementedError()

    def _ros_args(self) -> dict[str, str]:
        """Returns this node's ROS args, e.g. remaps and special parameters like namespace and name.

        .. seealso::

            `Passing ROS arguments to nodes via the command-line <https://docs.ros.org/en/jazzy/How-To-Guides/Node-arguments.html>`_

        Returns
        -------
        dict[str, str]
            A dict containing the
        """
        ros_args = dict(self.remaps)

        # Why do I hear mad hatter music???
        # See launch_ros/actions/node.py:495
        ros_args["__ns"] = self.namespace
        ros_args["__node"] = self.name

        return ros_args

    def _flat_params(self) -> dict[str, Any]:
        """Flattens this node's ROS parameters so they conform to what ROS expects.

        Returns
        -------
        dict[str, Any]
            A flattened dict containing param keys separated by '.'s and their values.

        Raises
        ------
        ValueError
            If any list inside the params contains a dict, although we don't recurse into lists. See `#152 <https://github.com/ros2/design/pull/152>`_ for further details.
        """
        ret = {}

        def delve(data: dict[str, Any], path: str):
            if isinstance(data, list):
                for val in data:
                    if isinstance(val, dict):
                        # See the following links for more details:
                        # https://github.com/ros2/launch_ros/blob/jazzy/launch_ros/launch_ros/utilities/normalize_parameters.py#L98
                        # https://answers.ros.org/question/322445/
                        raise ValueError("ROS2 does not support lists of dicts :(")

            if isinstance(data, dict):
                for key, val in data.items():
                    new_key = f"{path}.{key}" if path else key
                    delve(val, new_key)
            else:
                ret[path] = data

        delve(self.params, "")
        return ret

    def join(self, timeout: float = None) -> None:
        """Join this node and return once it is shut down. Return immediately if it is not running.

        Parameters
        ----------
        timeout : float, optional
            How long to wait in seconds. Wait forever if None.

        Raises
        ------
        TimeoutError
            If a timeout was set and the node is still running by the time it expires.
        """
        raise NotImplementedError()

    def start(self) -> None:
        """Start this node. Once this succeeds, :py:meth:`is_running` will return True."""
        raise NotImplementedError()

    def shutdown(self, reason: str, signum: int = signal.SIGTERM, timeout: float = 0.0) -> None:
        """Shutdown this node. Once this succeeds, :py:meth:`is_running` will return False.

        Parameters
        ----------
        reason : str
            A human-readable string describing why this node is being shutdown.
        signum : int, optional
            The signal that should be send to the node (if supported).
        timeout : float, optional
            How long to wait for the node to shutdown before returning. Don't wait if timeout is 0.0. Wait forever if timeout is None. 

        Raises
        ------
        TimeoutError
            If a timeout > 0 was set and the node did not shutdown before then.
        """
        raise NotImplementedError()

    def is_ros2_connected(self, timeout: float = 0.0) -> bool:
        """Check whether this node is registered within ROS.

        Parameters
        ----------
        timeout : float, optional
            How long to wait for the node to sign up with ROS. Wait forever if None.

        Returns
        -------
        bool
            True if the node can be discovered by ROS, False otherwise.
        """
        # Don't check is_running here as some implementations might use is_ros2_connected to
        # determine if the node is running
        from better_launch import BetterLaunch

        bl = BetterLaunch.instance()
        if not bl:
            return None

        # Check if the node shows up in the list of running ROS nodes
        try:
            now = time.time()
            while True:
                living_nodes = set(
                    ns + ("" if ns.endswith("/") else "/") + name
                    for name, ns in bl.shared_node.get_node_names_and_namespaces()
                )

                if self.fullname in living_nodes:
                    return True

                if timeout is not None and time.time() >= now + timeout:
                    return False

                time.sleep(0.1)
        except Exception:
            # Cannot check if the shared node was shut down
            return None

    def is_lifecycle_node(self, timeout: float = 0.0) -> bool:
        """Checks if this is a lifecycle node and initializes a : py:class:`LifecycleManager` if supported and not done so before.

        Note that if you simply want to check whether this node supports lifecycle management right now, check whether :py:meth:`lifecycle` is None will be considerably cheaper.

        Whether a node supports lifecycle management can only be known from outside once its process is started and it has registered with ROS. When this is called while the node is alive and it supports lifecycle management, a :py:class:`LifecycleManager` object will be initialized for it. This will persist even if the node is shutdown, but will obviously no longer provide useful functionality.

        Note that at the time of writing (Jazzy), the ROS node registers with ROS before the lifecycle topics are created. This makes sense of course, but also means that there is a short window where the node is registered with ROS but not a lifecycle node yet. This can be a problem, especially on slower devices like a Raspberry Pi 3. In these cases I advise you follow this pattern:

        .. code:: python

            node = Node(...)
            # Wait until the node is registered in ROS
            if node.is_ros2_connected(timeout=5.0):
                # Give the node some additional time to create its lifecycle topics
                if node.is_lifecycle_node(timeout=0.1):
                    # Now the node can be managed
                    node.lifecycle.transition(...)

        Parameters
        ----------
        timeout : float, optional
            How long to wait for the node to reveal its lifecycle capabilities. Wait forever if None.

        Returns
        -------
        bool
            True if the node supports lifecycle management, False otherwise.
        """
        if self._lifecycle_manager is None:
            if LifecycleManager.is_lifecycle(self, timeout=timeout):
                self._lifecycle_manager = LifecycleManager(self)

        return self._lifecycle_manager is not None

    @property
    def lifecycle(self) -> LifecycleManager:
        """Returns this node's :py:class:`LifecyceManager`.

        **Note:** make sure to call :py:meth:`is_lifecycle_node` before retrieving this object!

        Returns
        -------
        LifecycleManager
            The object used for managing this node's lifecycle. Will be None if lifecycle management is not supported or `is_lifecycle_node` has not been called before.
        """
        return self._lifecycle_manager

    def get_published_services(self) -> dict[str, list[str]]:
        """Get the ROS2 services provided by this node.

        Returns
        -------
        dict[str, list[str]]
            The service topics and message types. Will be empty if :py:meth:`is_ros2_connected` is False.
        """
        if not self.is_ros2_connected():
            return {}

        from better_launch import BetterLaunch

        bl = BetterLaunch.instance()
        services = bl.shared_node.get_service_names_and_types()
        fullname = self.fullname
        res = {}

        for srv_name, srv_types in services:
            if srv_name.startswith(fullname):
                res[srv_name] = srv_types

        return res

    def get_published_topics(self) -> dict[str, list[str]]:
        """Get the ROS2 topics published by this node.

        Returns
        -------
        dict[str, list[str]]
            The topics and their message types. Will be empty if :py:meth:`is_ros2_connected` is False.
        """
        if not self.is_ros2_connected():
            return {}

        from better_launch import BetterLaunch

        bl = BetterLaunch.instance()
        topics = bl.shared_node.get_publisher_names_and_types_by_node(self.name, self.namespace)
        return dict(topics)

    def get_subscribed_topics(self) -> dict[str, list[str]]:
        """Get the ROS2 topics this node is subscribed to.

        Returns
        -------
        dict[str, list[str]]
            The topics and their message types. Will be empty if :py:meth:`is_ros2_connected` is False.
        """
        if not self.is_ros2_connected():
            return {}

        from better_launch import BetterLaunch

        bl = BetterLaunch.instance()
        topics = bl.shared_node.get_subscriber_names_and_types_by_node(self.name, self.namespace)
        return dict(topics)

    def get_info_sheet(self) -> str:
        """Returns a summary of this node's information for display in a terminal.

        Returns
        -------
        str
            A detailed description of this node.
        """
        # ROS2 prints a lot of useless stuff and avoids the things that are interesting most of
        # the time, like who is actually subscribed where. Let's fix this!
        return "\n".join(
            [
                self._get_info_section_general(),
                self._get_info_section_config(),
                self._get_info_section_ros(),
            ]
        )

    def _get_info_section_general(self) -> str:
        status = "\x1b[92malive\x1b[0m" if self.is_running else "\x1b[91mdead\x1b[0m"
        return f"""\
\x1b[1m{self.name} ({self.__class__.__name__})\x1b[0m
  Status:    {status}
  Lifecycle: {self.lifecycle.current_stage.name if self.lifecycle else 'None'}
  Package:   {self.package}
  Command:   {self.executable}
  Namespace: {self.namespace}
"""

    def _get_info_section_config(self) -> str:
        return f"""\
\x1b[1mConfig\x1b[0m
  Node Args: {self.params}
  Remaps:    {self.remaps}
"""

    def _get_info_section_ros(self) -> str:
        if self.is_ros2_connected():
            from better_launch import BetterLaunch

            shared_node = BetterLaunch.instance().shared_node

            # Topics the node is publishing
            pubs = shared_node.get_publisher_names_and_types_by_node(
                self.name, self.namespace
            )
            pubs.sort()
            pubs_text = ""
            for topic, types in pubs:
                pubs_text += f"\n  {topic} [{', '.join(types)}]"

            # Topics the node is subscribed to
            subs = shared_node.get_subscriber_names_and_types_by_node(
                self.name, self.namespace
            )
            subs.sort()
            subs_text = ""
            for topic, types in subs:
                subs_text += f"\n  {topic} [{', '.join(types)}]"

            # Provided services
            services = shared_node.get_service_names_and_types_by_node(
                self.name, self.namespace
            )
            services.sort()
            services_text = ""
            for srv, types in services:
                services_text += f"\n  {srv} [{', '.join(types)}]"
        else:
            pubs_text = ""
            subs_text = ""
            services_text = ""

        # TODO don't use html
        return f"""\
\x1b[1mPublishers:\x1b[0m {pubs_text}

\x1b[1mSubscriptions:\x1b[0m {subs_text}

\x1b[1mServices:\x1b[0m {services_text}
"""

    def __repr__(self):
        return __class__.__name__ + " " + self.fullname
