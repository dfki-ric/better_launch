from typing import Any, Callable, Generator, Literal, TYPE_CHECKING
import importlib
import sys
import os
import signal
import inspect
import time
import re
import threading
import subprocess
from pathlib import Path
from concurrent.futures import Future, CancelledError, TimeoutError
from contextlib import contextmanager
import logging
import yaml

from rclpy.node import (
    Node as RosNode,
    Service as RosServiceProvider,
    Client as RosServiceClient,
    Publisher as RosPublisher,
    Subscription as RosSubscriber,
)
from rclpy.qos import QoSProfile, qos_profile_services_default
from ament_index_python.packages import get_package_prefix

if TYPE_CHECKING:
    # Surprisingly large imports, so we only import them if we actually need them
    from rclpy.action import (
        ActionServer as RosActionServer,
        ActionClient as RosActionClient,
    )

try:
    # For anonymous nodes
    import wonderwords

    _uuid_source = wonderwords.RandomWord(exclude_with_spaces=True)

    def _generate_uuid() -> str:
        return _uuid_source.word()

except ImportError:
    import uuid

    def _generate_uuid() -> str:
        return uuid.uuid4().hex

from better_launch.elements import (
    Group,
    AbstractNode,
    Node,
    Composer,
    Component,
    LifecycleStage,
    Ros2LaunchWrapper,
    ForeignNode,
    get_package_for_path,
    find_process_for_node,
    find_foreign_nodes,
)
from better_launch.utils.substitutions import (
    default_substitution_handlers,
    substitute_tokens,
)
from better_launch.utils.introspection import (
    find_function_frame,
    find_calling_frame,
    find_launchthis_function,
)
from better_launch.utils.better_logging import LogSink
from better_launch.ros.ros_adapter import ROSAdapter
from better_launch.ros import logging as roslog


_bl_singleton_instance = "__better_launch_instance"
_bl_include_args = "__better_launch_include_args"


class _BetterLaunchMeta(type):
    _singleton_future = Future()

    # Allows (and enforces) reusing an already existing BetterLaunch instance.
    # Important for launch file includes.
    def __call__(cls, *args, **kwargs):
        existing_instance = globals().get(_bl_singleton_instance, None)
        if existing_instance is not None:
            return existing_instance

        obj = cls.__new__(cls, *args, **kwargs)
        globals()[_bl_singleton_instance] = obj
        obj.__init__(*args, **kwargs)

        cls._singleton_future.set_result(obj)
        return obj

    def instance(cls) -> "BetterLaunch":
        """Immediately retrieve the BetterLaunch singleton instance.

        Returns
        -------
        BetterLaunch
            The BetterLaunch singleton instance, or None if it doesn't exist yet.
        """
        try:
            return cls._singleton_future.result(0.0)
        except TimeoutError:
            return None

    def wait_for_instance(cls, timeout: float = None) -> "BetterLaunch":
        """Retrieve the BetterLaunch singleton instance as soon as possible.

        Parameters
        ----------
        timeout : float, optional
            How long to wait for the singleton instance to appear. Wait forever if timeout is None. Don't wait at all if timeout is 0.0.

        Returns
        -------
        BetterLaunch
            The BetterLaunch singleton instance.

        Raises
        ------
        TimeoutError
            If the timeout has passed and no instance has appeared yet.
        """
        return cls._singleton_future.result(timeout)


class BetterLaunch(metaclass=_BetterLaunchMeta):
    """This should be all you need to create beautiful, simple and convenient launch files!"""

    _launchfile: str = None
    _launch_func_args: dict[str, Any] = {}

    def __init__(
        self,
        name: str = None,
        launch_args: dict[str, Any] = None,
        root_namespace: str = "/",
    ):
        """Note that BetterLaunch is a singleton: only the first invocation to `__init__` will succeed. All subsequent calls will return the previous instance. If you need access to the BetterLaunch instance outside your launch function, consider using one of the following classmethods instead:
        * :py:meth:`BetterLaunch.instance <_BetterLaunchMeta.instance>`
        * :py:meth:`BetterLaunch.wait_for_instance <_BetterLaunchMeta.wait_for_instance>`

        Parameters
        ----------
        name : str, optional
            The name of this instance, will default to the launchfile's filename.
        launch_args : dict, optional
            Override the launch arguments BetterLaunch has access to. By default this will be the launch function's arguments. These will mainly be used for passing to included launch files.
        root_namespace : str, optional
            The namespace of the root group.
        """
        if not name:
            if not BetterLaunch._launchfile:
                frame = find_calling_frame(self.__init__)
                BetterLaunch._launchfile = frame.filename
            name = os.path.basename(BetterLaunch._launchfile)

        # roslog.launch_config must be setup before instantiation of BetterLaunch
        self.logger = roslog.get_logger(name)

        if launch_args is not None:
            BetterLaunch._launch_func_args = launch_args

        # For those cases where we need to interact with ROS (e.g. service calls)
        self._ros_adapter: ROSAdapter = None

        if root_namespace is None:
            root_namespace = "/"
        root_namespace = "/" + root_namespace.strip("/")

        self._group_root = Group(None, root_namespace)
        self._group_stack = [self._group_root]

        self._composition_node = None

        # Allows to run traditional ros2 launch actions and descriptions
        self._ros2_launcher = None

        self._sigint_received = False
        self._sigterm_received = False
        self._shutdown_future = Future()
        self._shutdown_callbacks = []

        self.hello()

    def hello(self) -> None:
        """Prints our welcome message and some useful information.
        Note that this will not appear in the logs!
        """
        # Ascii art based on: https://asciiart.cc/view/10677
        msg = f"""
\x1b[1;20mBetter Launch is starting!\x1b[0m
Please fasten your seatbelts and secure all baggage underneath your chair.

Default log level is \x1b[34;20m{roslog.launch_config.level} ({logging.getLevelName(roslog.launch_config.level)})\x1b[0m
All log files can be found at
\x1b[34;20m{roslog.launch_config.log_dir}\x1b[0m

Takeoff in 3... 2... 1...

           *            ,:
    +                 ,' |
               +     /   :
       *          --'   /
+                \\/ /:/
            *     / ://_\\
       +       __/   /
  -            )'-. /
               ./  :\\
        *       /.' '
              '/'
   '          +
           .-"-
          (    )
       . .-'  '.
      ( (.   )8:
  .' _  / (_  ) '._
"""
        # We don't want to log this
        print(msg)
        self.logger.critical(f"Log files at {roslog.launch_config.log_dir}")

    def spin(self, exit_with_last_node: bool = True) -> None:
        """Join the BetterLaunch thread until it terminates. You do **not** need to call this if you're using the :py:meth:`launch_this` wrapper or the TUI.

        Parameters
        ----------
        exit_with_last_node : bool, optional
            If True this function will return when all nodes have been stopped.
        """
        if exit_with_last_node:
            while not self._shutdown_future.done():
                nodes = self.all_nodes(
                        include_components=True,
                        include_launch_service=True,
                        include_foreign=False
                )

                if all(not n.is_running for n in nodes):
                    self.shutdown("all nodes have stopped")
                    break

                # Sleep until every node has terminated, then check again
                for n in nodes:
                    n.join()
        else:
            try:
                self._shutdown_future.result()
            except (CancelledError, TimeoutError):
                pass

    def get_unique_name(self, name: str = "") -> str:
        """Adds a unique suffix to the provided string.

        Parameters
        ----------
        name : str, optional
            The string to use as the base.

        Returns
        -------
        str
            The passed in string with a unique suffix.
        """
        return name + "_" + _generate_uuid()

    def all_groups(self) -> list[Group]:
        """Returns a list of all in the order they were created.

        Returns
        -------
        list[Group]
            All groups added so far.
        """
        # Assemble all groups
        groups: list[Group] = [self.group_root]
        queue: list[Group] = [self.group_root]

        # Simplified breadth first search since we don't expect any loops
        while queue:
            g = queue.pop()
            groups.extend(g.children.values())
            queue.extend(g.children.values())

        return groups

    def all_nodes(
        self,
        *,
        include_components: bool = False,
        include_launch_service: bool = True,
        include_foreign: bool = False,
    ) -> list[AbstractNode]:
        """Returns a list of all nodes in the order they were added. Components will be added right after their composers. If a ROS2 launch service has been started it will be added at the very end.

        Parameters
        ----------
        include_components : bool, optional
            Whether to include :py:class:`Component` instances.
        include_launch_service : bool, optional
            Whether to include the ROS2 launch service wrapper if it was created.
        include_foreign : bool, optional
            Whether to include foreign nodes that have not been started by this launcher instance.

        Returns
        -------
        list[AbstractNode]
            A list of all nodes, sorted by when they were added.
        """
        nodes = []
        groups = self.all_groups()

        for g in groups:
            for n in g.nodes:
                nodes.append(n)
                if include_components and isinstance(n, Composer):
                    nodes.extend(n.managed_components)

        if include_launch_service and self._ros2_launcher:
            nodes.append(self._ros2_launcher)

        if include_foreign:
            nodes.extend(find_foreign_nodes())

        return nodes

    def query_node(
        self,
        fullname_regex: str,
        *,
        include_components: bool = True,
        include_launch_service: bool = False,
        include_foreign: bool = False,
    ) -> AbstractNode:
        """Retrieve the first node whos :py:meth:`AbstractNode.fullname` matches the provided regex.

        Parameters
        ----------
        name_regex : str
            The regex to match the nodes' full names against.
        include_components : bool, optional
            Whether to include components in the results, if any.
        include_launch_service : bool, optional
            Whether to include the ROS2 launch service in the result (if it exists).
        include_foreign : bool, optional
            Whether to include foreign nodes not created by this launcher.

        Returns
        -------
        AbstractNode
            The first node matching the provided regex, or None if none matched.
        """
        reg = re.compile(fullname_regex)
        for node in self.all_nodes(
            include_components=include_components,
            include_launch_service=include_launch_service,
            include_foreign=include_foreign,
        ):
            if reg.fullmatch(node.fullname):
                return node

        return None

    def query_nodes(
        self,
        name_regex: str,
        *,
        include_components: bool = True,
        include_launch_service: bool = False,
        include_foreign: bool = False,
    ) -> list[AbstractNode]:
        """Retrieve all nodes whos :py:meth:`AbstractNode.fullname` matches the provided regex.

        Parameters
        ----------
        name_regex : str
            The regex to match the nodes' full names against.
        include_components : bool, optional
            Whether to include components in the results, if any.
        include_launch_service : bool, optional
            Whether to include the ROS2 launch service in the result (if it exists).
        include_foreign : bool, optional
            Whether to include foreign nodes not created by this launcher.

        Returns
        -------
        list[AbstractNode]
            A list of all nodes matching the regex.
        """
        reg = re.compile(name_regex)
        return [
            node
            for node in self.all_nodes(
                include_components=include_components,
                include_launch_service=include_launch_service,
                include_foreign=include_foreign,
            )
            if reg.match(node.fullname)
        ]

    @staticmethod
    def ros_version() -> str:
        """Returns the name of the currently sourced ros version (i.e. *$ROS_VERSION*)."""
        return os.environ["ROS_DISTRO"]

    @property
    def launchfile(self) -> str:
        """The path of the (main) *better_launch* launchfile being executed."""
        return BetterLaunch._launchfile

    @property
    def launch_args(self) -> dict[str, Any]:
        """All key-value pairs that have been passed to the launch function."""
        return BetterLaunch._launch_func_args

    @property
    def ros_adapter(self) -> ROSAdapter:
        """Contains and runs a shared ROS2 node to interact with topics, services, etc. The adapter is instantiated lazily as it brings a major performance hit (about 6 MiB memory and a high CPU spike)."""
        if not self._ros_adapter or not self._ros_adapter._thread.is_alive():
            self._ros_adapter = ROSAdapter()

        return self._ros_adapter

    @property
    def shared_node(self) -> RosNode:
        """A ROS2 node instance that can be used for creating publishers, services, etc."""
        return self.ros_adapter.ros_node

    @property
    def group_root(self) -> Group:
        """The root group ("/")."""
        return self._group_stack[0]

    @property
    def group_tip(self) -> Group:
        """The most recent group."""
        return self._group_stack[-1]

    def find_group_for_namespace(self, namespace: str, create: bool = False) -> Group:
        """Find the group representing the passed namespace.

        Parameters
        ----------
        namespace : str
            The namespace in question.
        create : bool
            If True, create missing groups along the way.

        Returns
        -------
        Group
            The group representing the final segment of the namespace, or None if no such group exists and create == False.
        """
        if not namespace or namespace == "/":
            return self.group_root

        g = self.group_root

        for part in namespace.split("/"):
            child = g.children.get(part)
            if not child:
                if not create:
                    return None

                child = Group(g, part)
                g.add_child(child)

            g = child

        return g

    def _on_sigint(self, sig: int, frame: inspect.FrameInfo) -> None:
        if not self._sigint_received:
            self.logger.warning("Received (SIGINT), forwarding to child processes...")
            self._sigint_received = True
            self.shutdown("user interrupt", signal.SIGINT)
        else:
            self.logger.warning("Received (SIGINT) again, escalating to sigterm")
            self._on_sigterm(sig, frame)

    def _on_sigterm(self, sig: int, frame: inspect.FrameInfo) -> None:
        if self._sigterm_received:
            try:
                self.logger.critical("(SIGTERM) received again, terminating process")
            finally:
                sys.exit(-1)

        self._sigterm_received = True
        self.logger.error("Using (SIGTERM) can result in orphaned processes!")

        # Final chance for the processes to shut down, but we will no longer wait
        self.shutdown("received (SIGTERM)", signal.SIGTERM)

        if not self.is_shutdown:
            self._shutdown_future.cancel()

    @property
    def is_shutdown(self) -> bool:
        """Whether *better_launch* has shutdown."""
        return self._shutdown_future.done()

    def add_shutdown_callback(self, callback: Callable[[], Any]) -> None:
        """Adds a callback which will be called when *better_launch* shuts down.

        Parameters
        ----------
        callback : Callable
            The callback to call on shutdown.
        """
        self._shutdown_callbacks.append(callback)

    def shutdown(self, reason: str = None, signum: int = signal.SIGTERM) -> None:
        """Ask all nodes to shutdown and terminate the internal ROS2 thread. Any subsequent calls to BetterLaunch member functions, including this one, may fail. This will typically be called when you want to terminate your launch file.

        Parameters
        ----------
        reason : str, optional
            A human-readable string explaining the reason for the shutdown. If not given this will be requitted with a warning.
        signum : int, optional
            The signal to send to child processes.
        """
        if reason is None:
            try:
                frame = find_function_frame(self.shutdown)
                self.logger.warning(
                    f"Shutdown was called from {frame.function}, but no reason was given"
                )
            except Exception:
                self.logger.warning(
                    "Shutdown was called without providing a reason and the calling frame could not be determined"
                )
        else:
            self.logger.info(f"Shutdown: {reason}")

        # Tell all nodes to shut down
        for n in self.all_nodes(
            include_components=False, include_launch_service=True, include_foreign=False
        ):
            try:
                n.shutdown(reason, signum)
            except NotImplementedError:
                pass
            except Exception as e:
                self.logger.error(
                    f"Node {n.name} raised an exception during shutdown: {e}"
                )

        try:
            if self._ros_adapter:
                self._ros_adapter.shutdown()
                self._ros_adapter = None
        except Exception as e:
            self.logger.error(f"RosAdapter raised an exception during shutdown: {e}")

        # If we launched extra ROS2 actions tell the launch service to shut down, too
        if self._ros2_launcher is not None:
            try:
                self._ros2_launcher.shutdown(reason, signum)
            except Exception as e:
                self.logger.error(
                    f"ROS2 launch service raised an exception during shutdown: {e}"
                )

        try:
            self._shutdown_future.set_result(None)
        except Exception:
            pass

        # Call any callbacks, but only once
        callbacks = self._shutdown_callbacks
        self._shutdown_callbacks = []

        for cb in callbacks:
            try:
                cb()
            except Exception as e:
                self.logger.warning(f"Shutdown callback failed: {e}")

    def find(
        self,
        package: str = None,
        filename: str = None,
        subdir: str = None,
        *,
        substitutions: bool = True,
    ) -> str:
        """Resolve a path to a file or package.

        If the `filename` is absolute, all other arguments will be ignored and the filename will be returned.

        If `package` is provided, the corresponding ROS2 package path will be used as the base path. Else we attempt to locate the current launch file's package by searching its directory and parent directories for a `package.xml`. If the package cannot be determined the current working dir is used as the base path.

        If neither `subdir` nor `filename` is provided the base path will be returned.

        If `filename` is provided but `subdir` is not, the base path will be searched recursively for the given filename. Otherwise, `subdir` will be used to locate valid candidate files and directories within the base path, allowing patterns like `**/lib/` (any lib folder) and `*.py` (any python file).

        If only `subdir` is provided but not `filename`, the first candidate is returned. Otherwise the discovered candidates will be searched for the given filename.

        Parameters
        ----------
        package : str, optional
            Name of a ROS2 package to resolve.
        filename : str, optional
            Name of a file to look for.
        subdir : str, optional
            A glob pattern to locate subdirectories and files. See the `pathlib pattern language <https://docs.python.org/3/library/pathlib.html#pathlib-pattern-language>`_ for details.
        substitutions : bool, optional
            If True, text substitution strings within the package and base path will be resolved (see :py:meth:`resolve_strin​g`).

        Returns
        -------
        str
            A resolved path.

        Raises
        ------
        ValueError
            If `package` contains path separators, or if a `filename` is provided but could not be found within base path.
        """
        resolve = None
        if substitutions:
            resolve = self.resolve_string

        if filename:
            if resolve:
                filename = resolve(filename)

            if os.path.isabs(filename):
                return filename

        if not package:
            package, _ = get_package_for_path(os.path.dirname(self.launchfile))

        if package:
            if "/" in package or os.pathsep in package:
                raise ValueError(
                    f"Package must be a single name, not a path ({package})"
                )
            base_path = get_package_prefix(package)
        else:
            base_path = os.getcwd()

        if resolve:
            base_path = resolve(base_path)

        if not filename and not subdir:
            return base_path

        if not subdir:
            subdir = "**"

        for candidate in Path(base_path).glob(subdir):
            if not filename:
                # Return the first candidate
                return str(candidate.resolve().absolute())

            if candidate.is_file() and candidate.match(f"**/{filename}"):
                # We found a match
                return str(candidate.resolve().absolute())

            elif candidate.is_dir():
                # Candidate is a dir, search the filename within
                ret = next(candidate.glob(f"**/{filename}"), None)
                if ret:
                    return str(ret.resolve().absolute())

        raise ValueError(
            f"Could not find file or directory (filename={filename}, package={package}, glob={subdir})"
        )

    def resolve_string(self, s: str) -> str:
        """Replaces a variety of special strings in the provided string, usually a path.

        This is similar to what ROS1 could do when resolving paths in XML launch files. Substitutions always have the form `$(<substitution-type> <substitution-args>)`. Substitutions can also be nested, so the following is possible:

        ``$(eval $(arg x) * 5)``  ->  if x=2, this will be resolved to 10

        Note that the underlying algorithm will likely fail if it encounters additional brackets within the string.

        The following substitutions are supported:
        * `$(find <filename> <package> <subdir>)`: return the result of :py:meth:`find`. Note that substitution arguments are always sequential (not kwargs).
        * `$(arg <name> <default>)`: return the value of an argument passed to the launch function or `<default>` if it doesn't exist. Raises KeyError if no default is provided and no default was provided.
        * `$(param <full-node-name> <param>)`: retrieves the value of the ROS parameter `<param>` from the `<full-node-name>` (i.e. namespace + node name). Raises KeyError if the node does not exist or ValueError if the node does not have the specified parameter.
        * `$(env <key> <default>)`: return the value of the environment variable `<key>` or `<default>` if it doesn't exist. Raises KeyError if no default is provided and no default was provided.
        * `$(eval <python-snippet>)`: returns the result from evaluating the provided `<python-snippet>`. Typical use cases include simple math and assembling strings. **Note** that this indeed uses python's :py:func:`eval`.

        Parameters
        ----------
        s : str
            The string to apply substitutions to.

        Returns
        -------
        str
            The string with all substitutions involved.
        Raises
        ------
        KeyError, ValueError
            Depending on the substitution that failed.
        """
        if not s:
            return ""

        return substitute_tokens(s, default_substitution_handlers("full"))

    def load_params(
        self,
        package: str,
        configfile: str,
        subdir: str = None,
        *,
        node_or_namespace: str | Node = None,
    ) -> dict[str, Any]:
        """Load parameters from a yaml file located through :py:meth:`find`.

        If the config only contains a `ros__parameters` section the entire config is returned regardless of whether `node_or_namespace` was passed. Otherwise, if `node_or_namespace` is provided, the loaded config dict is searched for a matching section. If no matching section can be found a ValueError will be raised.

        The following wildcards are supported for parameter sections:
        * `/**`: matches any number of tokens, may be followed by additional tokens and a node name
        * `/*`: skips a single namespace token, or ignores the node's name if at the end

        Note that *better_launch* could not care less whether you put `ros__parameters` in your configs - if it is there it will be silently discarded.

        .. seealso::

            `ROS2 design doc on wildcards <https://github.com/ros2/design/blob/gh-pages/articles/160_ros_command_line_arguments.md#multiple-parameter-assignments>`_

        Parameters
        ----------
        package : str
            A package to search for the config file. May be `None` (see :py:meth:`find`).
        configfile : str
            The name of the config file to locate.
        subdir : str, optional
            A path fragment that the config file must be located in.
        node_or_namespace : str | Node, optional
            Used to specifiy which section of the config to return.

        Returns
        -------
        dict[str, Any]
            The key-value pairs from the config.

        Raises
        ------
        ValueError
            If the path cannot be resolved, if `node_or_namespace` is supplied and no matching section could be found, or if a substitution failed.
        IOError
            If the config file could not be read.
        """
        path = self.find(package, configfile, subdir)

        with open(path) as f:
            params = yaml.safe_load(f)

        if "ros__parameters" in params:
            # Return the entire config if it doesn't contain sections for different nodes/namespaces
            return params["ros__parameters"]

        final_params = {}

        if node_or_namespace:
            ns = node_or_namespace
            if isinstance(ns, AbstractNode):
                ns = ns.fullname

            ns = ns.strip("/")

            # See https://github.com/ros2/design/blob/gh-pages/articles/160_ros_command_line_arguments.md
            def path_to_regex(path: str) -> str:
                parts = path.strip("/").split("/")
                regex_parts = []

                for part in parts:
                    if part == "**":
                        # Match any number of tokens
                        regex_parts.append(r".*")
                    elif part == "*":
                        # Match a single token
                        regex_parts.append(r"[^/]+")
                    else:
                        # Regular token
                        regex_parts.append(part)

                # We do NOT start with a slash as only the node name could be specified
                return "^" + "/".join(regex_parts) + "$"

            # According to the above design document, params files are not allowed to have nesting,
            # (e.g. my_namespace/: other_namespace/node: ros__parameters), so no need to delve
            for key in params.keys():
                pattern = path_to_regex(key)
                if re.match(pattern, ns) is not None:
                    final_params.update(params[key])
                    # Don't break as there can be multiple matching entries due to wildcards
                    # See https://docs.ros.org/en/jazzy/How-To-Guides/Node-arguments.html

            if not final_params:
                # We didn't find any matching parameters, so this either doesn't contain a section
                # for this node, or it is not a ros parameters file
                raise ValueError(f"No param section matching '{ns}'")
        else:
            # No node or namespace provided, so we don't know which section we should resolve
            final_params = params

        # Discard the ros__parameters section if it's at the root
        if "ros__parameters" in final_params:
            final_params.update(final_params["ros__parameters"])
            final_params.pop("ros__parameters", None)

        return final_params

    def get_ros_message_type(self, message_string: str) -> type:
        """Loads a ROS2 message type from a string representation.

        Message representations must follow the pattern `<package>/<type>/<message>`, where
        * <package> is the ROS2 package that defines the message.
        * <type> is the type of message, typically one of `msg`, `srv` or `action`.
        * <message> is the name of the message itself with proper capitalization.

        Parameters
        ----------
        message_string : str
            A message representation of the form `<package>/<type>/<message>`.

        Returns
        -------
        type
            The message class.

        Raises
        ------
        ImportError
            If the message type could not be imported.
        """
        module_name, message_name = message_string.rsplit("/", maxsplit=1)
        module = importlib.import_module(module_name.replace("/", "."))
        return getattr(module, message_name)

    def wait_for_topic(
        self,
        topic: str,
        timeout: float = None,
    ) -> bool:
        """Wait for the specified topic to appear.

        Parameters
        ----------
        topic : str
            The full path of the topic to wait for.
        timeout : float, optional
            How long to wait for the topic. Wait forever if None.

        Returns
        -------
        bool
            True if the topic appeared within the timeout, False otherwise.
        """
        now = time.time()
        while True:
            published = self.shared_node.get_topic_names_and_types()
            for name, _ in published:
                if name == topic:
                    return True

            if timeout is not None and time.time() > now + timeout:
                return False

            time.sleep(0.1)

    def wait_for_service(
        self,
        service: str,
        timeout: float = None,
    ) -> bool:
        """Wait for the specified service to appear.

        Parameters
        ----------
        service : str
            The full path of the service to wait for.
        timeout : float, optional
            How long to wait for the service. Wait forever if None.

        Returns
        -------
        bool
            True if the service appeared within the timeout, False otherwise.
        """
        now = time.time()
        while True:
            published = self.shared_node.get_service_names_and_types()
            for name, _ in published:
                if name == service:
                    return True

            if timeout is not None and time.time() > now + timeout:
                return False

            time.sleep(0.1)

    def subscriber(
        self,
        topic: str,
        message_type: type,
        callback: Callable[[Any], None],
        qos_profile: QoSProfile | int = 10,
    ) -> RosSubscriber:
        """Create a ROS2 subscriber to receive messages.

        Parameters
        ----------
        topic : str
            The topic to listen on for messages.
        message_type : str | type
            The type of the messages that will be received. Strings must follow the pattern `<package>/msg/<message>`.
        callback : Callable[[Any], Any]
            A function that will be called whenever a message is received.
        qos_profile : QoSProfile | int, optional
            A quality of service profile that changes how the publisher handles connections and retains data.

        Returns
        -------
        RosSubscriber
            The subscriber object. Although not required for Jazzy and below, it is recommended to keep a reference.
        """
        if isinstance(message_type, str):
            message_type = self.get_ros_message_type(message_type)

        return self.shared_node.create_subscription(
            message_type,
            topic,
            callback,
            qos_profile=qos_profile,
        )

    def publisher(
        self, topic: str, message_type: str | type, qos_profile: QoSProfile | int = 10
    ) -> RosPublisher:
        """Create a ROS2 publisher using the :py:meth:`shared_node`.

        Parameters
        ----------
        topic : str
            The topic to publish messages on.
        message_type : str | type
            The message type that will be published. Strings must follow the pattern `<package>/msg/<message>`.
        qos_profile : QoSProfile | int, optional
            A quality of service profile that changes how the publisher handles connections and retains data.

        Returns
        -------
        RosPublisher
            The publisher object. Although not required for Jazzy and below, it is recommended to keep a reference.
        """
        if isinstance(message_type, str):
            message_type = self.get_ros_message_type(message_type)

        return self.shared_node.create_publisher(
            message_type,
            topic,
            qos_profile=qos_profile,
        )

    def publish_message(
        self,
        topic: str,
        message_type: str | type,
        message_args: dict[str, Any],
        qos_profile: QoSProfile | int = 10,
        *,
        time_to_publish: float = 1.0,
    ) -> None:
        """Convenience method to publish a single message. The publisher will be destroyed once the message has been published. If you plan to publish additional messages, use :py:meth:`publisher` instead and use the instance.

        Parameters
        ----------
        topic : str
            The topic to publish messages on.
        message_type : str | type
            The message type that will be published. Strings must follow the pattern `<package>/msg/<message>`.
        message_args : dict[str, Any]
            The keyword arguments from which the message will be constructed.
        qos_profile : QoSProfile | int, optional
            A quality of service profile that changes how the publisher handles connections and retains data.
        time_to_publish: float, optional
            How long to give the publisher to submit the message. Expect the message to get lost if you set this to 0.
        """
        if isinstance(message_type, str):
            message_type: type = self.get_ros_message_type(message_type)

        pub = self.publisher(topic, message_type, qos_profile)
        msg = message_type(**message_args)
        pub.publish(msg)

        if time_to_publish is not None and time_to_publish > 0.0:
            time.sleep(time_to_publish)

        pub.destroy()

    def service(
        self,
        topic: str,
        service_type: str | type,
        callback: Callable[[Any], Any],
        qos_profile: QoSProfile = None,
    ) -> RosServiceProvider:
        """Create a ROS2 service provider using the :py:meth:`shared_node`.

        Parameters
        ----------
        topic : str
            The topic the service will live on.
        service_type : str | type
            The service's message type. Strings must follow the pattern `<package>/srv/<message>`.
        callback : Callable[[Any], Any]
            The function that will handle any requests to the service. The type of the request will be of type `service_type.Request`.
        qos_profile : QoSProfile, optional
            A quality of service profile that changes how the service handles connections.

        Returns
        -------
        RosServiceProvider
            The service object. Although not required for Jazzy and below, it is recommended to keep a reference.
        """
        if isinstance(service_type, str):
            service_type = self.get_ros_message_type(service_type)

        if not qos_profile:
            qos_profile = qos_profile_services_default

        return self.shared_node.create_service(
            service_type,
            topic,
            callback,
            qos_profile=qos_profile,
        )

    def service_client(
        self,
        topic: str,
        service_type: str | type,
        timeout: float = 5.0,
        qos_profile: QoSProfile = None,
    ) -> RosServiceClient:
        """Create a ROS2 service client that can be used to call a service.

        Parameters
        ----------
        topic : str
            The service topic to post requests on.
        service_type : str | type
            The service's message type. Strings must follow the pattern `<package>/srv/<message>`.
        timeout : float, optional
            Time to wait for the service to become available. Ignored if <= 0.
        qos_profile : QoSProfile, optional
            A quality of service profile that changes how the service handles connections.

        Returns
        -------
        RosServiceClient
            The client object. Although not required for Jazzy and below, it is recommended to keep a reference.

        Raises
        ------
        TimeoutError
            If the service did not become available within the specified timeout.
        """
        if isinstance(service_type, str):
            service_type = self.get_ros_message_type(service_type)

        if not qos_profile:
            qos_profile = qos_profile_services_default

        client = self.shared_node.create_client(
            service_type, topic, qos_profile=qos_profile
        )
        if timeout > 0.0:
            if not client.wait_for_service(timeout):
                raise TimeoutError(
                    f"Service client timed out ({topic}, {service_type})"
                )
        return client

    def call_service(
        self,
        topic: str,
        service_type: str | type,
        request_args: dict[str, Any] | Any = None,
        *,
        timeout: float = 5.0,
        qos_profile: QoSProfile = None,
        call_async: bool = False,
    ) -> Any:
        """Makes a single service request and returns the result. The client is destroyed once the request has been handled. If you plan to make additional requests, use :py:meth:`service_client` instead.

        Parameters
        ----------
        topic : str
            The service topic to post requests on.
        service_type : str | type
            The service's message type. Strings must follow the pattern `<package>/srv/<message>`.
        request_args : dict[str, Any] | Any
            The keyword arguments from which the request message will be constructed. May also be an instance of `service_type.Request`.
        timeout : float, optional
            Time to wait for the service to become available. Ignored if <= 0.
        qos_profile : QoSProfile, optional
            A quality of service profile that changes how the service handles connections.
        call_async : bool, optional
            If True, make the service call async and return a :py:class:`rclpy.task.Future` instead.

        Returns
        -------
        Any
            A :py:class:`rclpy.task.Future` if `call_async` is True, otherwise the result of the service call of type `service_type.Request`.

        Raises
        ------
        TimeoutError
            If the service did not become available within the specified timeout.
        """
        if isinstance(service_type, str):
            service_type = self.get_ros_message_type(service_type)

        if isinstance(request_args, service_type.Request):
            req = request_args
        elif isinstance(request_args, dict):
            req = service_type.Request(**request_args)
        else:
            req = service_type.Request()

        srv = self.service_client(topic, service_type, timeout, qos_profile)

        if call_async:
            res = srv.call_async(req)
            res.add_done_callback(lambda f: srv.destroy())
        else:
            res = srv.call(req)

        return res

    def action_server(
        self,
        topic: str,
        action_type: str | type,
        callback: Callable[[Any], Any],
        qos_profile: QoSProfile = None,
    ) -> "RosActionServer":
        """Create a ROS2 action server using the :py:meth:`shared_node`.

        Parameters
        ----------
        topic : str
            The topic namespace to provide the action interface on.
        action_type : str | type
            The type of the actions to be handled. Strings must follow the pattern `<package>/action/<message>`.
        callback : Callable[[Any], Any]
            A function that will handle incoming action requests. The type of the requests will be of type :py:func:`rclpy.action.server.ServerGoalHandle` and contain an `action_type.Goal`.
        qos_profile : QoSProfile, optional
            A quality of service profile that changes how the action server handles connections and retains data.

        Returns
        -------
        RosActionServer
            The action server object. Although not required for Jazzy and below, it is recommended to keep a reference.
        """
        from rclpy.action import ActionServer

        if isinstance(action_type, str):
            action_type = self.get_ros_message_type(action_type)

        if not qos_profile:
            qos_profile = qos_profile_services_default

        return ActionServer(
            self.shared_node,
            action_type,
            topic,
            callback,
            goal_service_qos_profile=qos_profile,
            result_service_qos_profile=qos_profile,
            cancel_service_qos_profile=qos_profile,
        )

    def action_client(
        self,
        topic: str,
        action_type: str | type,
        timeout: float = 5.0,
        qos_profile: QoSProfile = None,
    ) -> "RosActionClient":
        """Create a ROS2 action client to execute long-running actions.

        Parameters
        ----------
        topic : str
            The topic namespace on which the action interface is provided.
        action_type : str | type
            The type of actions the action server handles. Strings must follow the pattern `<package>/action/<message>`.
        timeout : float, optional
            Time to wait for the action server to become available. Ignored if <= 0.
        qos_profile : QoSProfile, optional
            A quality of service profile that changes how the action server handles connections and retains data.

        Returns
        -------
        RosActionClient
            The action client object. Although not required for Jazzy and below, it is recommended to keep a reference.

        Raises
        ------
        TimeoutError
            If the action server did not become available within the specified timeout.
        """
        # Lazy import, these add a lot of overhead
        from rclpy.action import ActionClient

        if isinstance(action_type, str):
            action_type = self.get_ros_message_type(action_type)

        if not qos_profile:
            qos_profile = qos_profile_services_default

        client = ActionClient(
            self.shared_node,
            action_type,
            topic,
            goal_service_qos_profile=qos_profile,
            result_service_qos_profile=qos_profile,
            cancel_service_qos_profile=qos_profile,
        )

        if timeout > 0.0:
            if not client.wait_for_server(timeout):
                raise TimeoutError(f"Action client timed out ({topic}, {action_type})")
        return client

    @contextmanager
    def group(self, namespace: str) -> Generator[Group, None, None]:
        """Groups are used to bundle nodes into namespaces. While they influence the nodes' topics
        and service name, they have no runtime functionality.

        Groups are intended to be used as context objects and can be nested. Note that starting a
        new root branch (i.e. a group starting with "/") is valid and will change subsequent groups
        for the duration of the context window.

        .. code:: python

            bl = BetterLaunch()
            with bl.group("outer"):
                # Unless included in another group, "outer" will be attached to "/"
                with bl.group("inner/sanctum"):
                    # Regular nesting, nodes will live within "/outer/inner/sanctum"
                    bl.node(...)
                with bl.group("/evil/tower"):
                    # New root branch, nodes will live within "/evil/tower"
                    bl.node(...)
                # Root branch exited, nodes will live within "/outer" once again
                bl.node(...)

        .. seealso::

            * :py:meth:`group_root`
            * :py:meth:`group_tip`

        Parameters
        ----------
        namespace : str
            The group's namespace.

        Yields
        ------
        Generator[Group, None, None]
            Places the group on the group stack and yields it. Exiting the context will pop the group from the group stack.

        Raises
        ------
        RuntimeError
            If the group is created within a compose context.
        """
        if self._composition_node:
            raise ValueError("Cannot create a group inside a compose context")

        # It's possible to start a new root branch, especially when including launch files. Once
        # we exit that branch the previous stack should be restored
        old_stack = self._group_stack[:]
        if namespace.startswith("/"):
            self._group_stack = [self._group_root]

        tip = self.group_tip
        for token in namespace.strip("/").split("/"):
            if token in tip.children:
                branch = tip.children[token]
            else:
                branch = Group(tip, token)
                tip.add_child(branch)

            self._group_stack.append(branch)
            tip = branch

        try:
            yield tip
        finally:
            # Restore the old stack.
            # Since it is possible to start a new root branch or open up multiple/namespaces/at/
            # once we replace the entire stack rather than only removing elements from the end
            self._group_stack = old_stack

    # There's no real need to have this as a member of BetterLaunch, but it's kind of expected to
    # be there. By making it a class method it can still be used without a BL instance.
    @classmethod
    def exec(cls, cmd: str | list[str]) -> str:
        """Run the specified command and return its output. The command can either be an absolute path to an executable or any file found on `PATH`.

        Parameters
        ----------
        cmd : str | list[str]
            The command to run. If a string is passed it will be split on spaces to separate the command from its arguments. Pass a list instead to have more control over which arguments to treat as a single argument.

        Returns
        -------
        str
            The output of the command without the trailing newline.

        Raises
        ------
        subprocess.CalledProcessError
            If the command had a non-zero exit code. See the raised error's `returncode` and `output` attributes for details.
        """
        if isinstance(cmd, str):
            cmd = cmd.split(" ")

        return (
            subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().rstrip("\n")
        )

    def node(
        self,
        package: str,
        executable: str,
        name: str = None,
        *,
        remaps: dict[str, str] = None,
        params: str | dict[str, Any] = None,
        cmd_args: list[str] = None,
        env: dict[str, str] = None,
        isolate_env: bool = False,
        log_level: int = logging.INFO,
        output: LogSink | set[LogSink] = "screen",
        anonymous: bool = False,
        hidden: bool = False,
        on_exit: Callable = None,
        max_respawns: int = 0,
        respawn_delay: float = 0.0,
        use_shell: bool = False,
        autostart_process: bool = True,
        ros_waittime: float = 3.0,
        lifecycle_waittime: float = 0.01,
        lifecycle_target: LifecycleStage = LifecycleStage.ACTIVE,
        raw: bool = False,
    ) -> Node:
        """Create a new ROS2 node process. The bread and butter of every ROS setup!

        Note that this method also handles lifecycle nodes (they REALLY should have a common interface). Note that especially for lifecycle nodes you probably want `autostart_process == True`, otherwise there lifecycle management will not exist. With `autostart_process == True`, a lifecycle node will automatically advance to `lifecycle_target` once it is up. Otherwise you can also call :py:meth:`Node.start` later.

        The `ROS2 documentation <https://docs.ros.org/en/rolling/How-To-Guides/Node-arguments.html>`_ can provide some additional information regarding `params`, `remaps`, and so on.

        Parameters
        ----------
        package : str
            The package providing the node.
        executable : str
            The executable that should be run.
        name : str, optional
            The name you want the node to be known as. If `None`, a name will be derived from `package` and `executable` and `anonymous` will be set to True.
        remaps : dict[str, str], optional
            Tells the node to replace any topics it wants to interact with according to the provided dict.
        params : str | dict[str, Any], optional
            Any ROS parameters you want to pass to the node. These are the args you would typically have to declare in your launch file. A string will be interpreted as a path to a yaml file which will be lazy loaded using :py:meth:`BetterLaunch.load_params`.
        cmd_args : list[str], optional
            Additional command line arguments to pass to the node.
        env : dict[str, str], optional
            Additional environment variables to set for the node's process. The node process will merge these with the environment variables of the better_launch host process unless :py:meth:`isolate_env` is True.
        isolate_env : bool, optional
            If True, the node process' env will not be inherited from the parent process and only those passed via `env` will be used. Be aware that this can result in many common things to not work anymore since e.g. keys like *PATH* will be missing.
        log_level : int, optional
            The minimum severity a logged message from this node must have in order to be published. This will be added to the cmd_args unless it is None.
        output : LogSink | set[LogSink], optional
            Determines if and where this node's output should be directed. Common choices are `screen` to print to terminal, `log` to write to a common log file, `own_log` to write to a node-specific log file, and `none` to not write any output anywhere. See :py:meth:`configure_logger` for details.
        anonymous : bool, optional
            If True, the node name will be appended with a unique suffix to avoid name conflicts.
        hidden : bool, optional
            If True, the node name will be prepended with a "_", hiding it from common listings.
        on_exit : Callable, optional
            A function to call when the node's process terminates (after any possible respawns).
        max_respawns : int, optional
            How often to restart the node process if it terminates.
        respawn_delay : float, optional
            How long to wait before restarting the node process after it terminates.
        use_shell : bool, optional
            If True, invoke the node executable via the system shell. While this gives access to the shell's builtins, this has the downside of running the node inside a "mystery program" which is platform and user dependent. Generally not advised.
        autostart_process : bool, optional
            If True, start the node process before returning from this function.
        ros_waittime : float, optional
            How long to wait for the node to register with ROS. This should cover the time between the process starting and the node initializing itself. Set negative to wait indefinitely. Set to None to avoid the check entirely. Will do nothing if `autostart_process` is False.
        lifecycle_waittime : float, optional
            How long to wait for the node's lifecycle management to come up. This should cover the time between the node initializing itself (see `ros_waittime`) and creating its additional topics and services. While neglible on modern computers, slower devices and embedded systems may experience a noticable delay here. Set negative to wait indefinitely. Set to None to avoid the check entirely. Will do nothing if `autostart_process` is False.
        lifecycle_target : LifecycleStage, optional
            The lifecycle stage to bring the node into after starting. Has no effect if `autostart_process` is False or if the node does not appear to be a lifecycle node after waiting `ros_waittime + lifecycle_waittime`.
        raw : bool, optional
            If True, don't treat the executable as a ROS2 node and avoid passing it any command line arguments except those specified.

        Returns
        -------
        Node
            The node object wrapping the node process.

        Raises
        ------
        RuntimeError
            If you try to add a node withing a :py:meth:`compose` context.
        """
        if self._composition_node:
            raise RuntimeError("Cannot add nodes inside a composition node")

        if not name:
            name = f"{package}_{executable}"
            anonymous = True

        if anonymous:
            name = self.get_unique_name(name)

        if hidden and not name.startswith("_"):
            name = "_" + name

        group = self.group_tip
        namespace = group.assemble_namespace()

        node = Node(
            package,
            executable,
            name,
            namespace,
            remaps=remaps,
            params=params,
            cmd_args=cmd_args,
            env=env,
            isolate_env=isolate_env,
            log_level=log_level,
            output=output,
            on_exit=on_exit,
            max_respawns=max_respawns,
            respawn_delay=respawn_delay,
            use_shell=use_shell,
            raw=raw,
        )

        group.add_node(node)
        if autostart_process:
            node.start()

            if ros_waittime is not None and node.is_ros2_connected(ros_waittime):
                if (
                    lifecycle_target not in (None, LifecycleStage.PRISTINE)
                    and lifecycle_waittime is not None
                    and node.is_lifecycle_node(lifecycle_waittime)
                ):
                    node.lifecycle.transition(lifecycle_target)

        return node

    @contextmanager
    def compose(
        self,
        name: str = None,
        language: str = "cpp",
        variant: Literal["normal", "multithreading", "isolated"] = "normal",
        *,
        reuse_existing: bool = True,
        component_remaps: dict[str, str] = None,
        anonymous: bool = False,
        hidden: bool = False,
        autostart_process: bool = True,
        ros_waittime: float = 3.0,
        output: LogSink | set[LogSink] = "screen",
    ) -> Generator[Composer, None, None]:
        """Creates a composer node which can be used to load :py:class:`Component`s. Components can be instantiated directly, or preferably via :py:meth:`component`. Only components can reside within a composer.

        Existing composers can be reused even if they have been created outside of *better_launch*. See :py:class:`Composer` for further details.

        This method should be used as a context, e.g.

        .. code:: python

            bl = BetterLaunch()
            with bl.compose("my-composer"):
                bl.component("my_package", "mystuff:TheComponentOfDreams", "normal-component")

        Parameters
        ----------
        name : str, optional
            The name you want the composer to be known as. `anonymous` will be set to True if no name is provided.
        language : str, optional
            The implementation of the standard composer you want to use. Ignored if `reuse_existing` is True and a matching node is found.
        variant : Literal["normal", "multithreading", "isolated"], optional
            ROS2 provides special composers for components that need multithreading or should be isolated from the rest. Ignored if `reuse_existing` is True and a matching node is found.
        reuse_existing : bool, optional
            If True and a node matching the current namespace and provided name is found, it will be used instead of creating a new node. This will even work for composers not created through better_launch, although in that case it won't be possible to stop them.
        component_remaps : dict[str, str], optional
            Any remaps you want to apply to all *components* loaded into this composer.
        anonymous : bool, optional
            If True, the composer name will be appended with a unique suffix to avoid name conflicts. `reuse_existing` will be set to False in this case.
        hidden : bool, optional
            If True, the composer name will be prepended with a "_", hiding it from common listings.
        autostart_process : bool, optional
            If True, start the composer process before returning from this function. Note that setting this to False for a composer will make it unusable as a context object, since you won't be able to load any components.
        ros_waittime : float, optional
            How long to wait for the composer to register with ROS. This should cover the time between the process starting and the composer initializing itself. Set negative to wait indefinitely. Will do nothing if `autostart_process` is False.
        output : LogSink | set[LogSink], optional
            Determines if and where this node's output should be directed. Common choices are `screen` to print to terminal, `log` to write to a common log file, `own_log` to write to a node-specific log file, and `none` to not write any output anywhere. See :py:meth:`configure_logger` for details.

        Yields
        ------
        Generator[Composer, None, None]
            Sets the composition flag and yields the composer.

        Raises
        ------
        RuntimeError
            If you try to create a composer within a :py:func:`compose` context.
        """
        if self._composition_node is not None:
            raise RuntimeError("Cannot nest composition nodes")

        if not name:
            name = "composer"
            anonymous = True

        if anonymous:
            name = self.get_unique_name(name)
            reuse_existing = False

        if hidden and not name.startswith("_"):
            name = "_" + name

        group = self.group_tip
        namespace = group.assemble_namespace()

        node_ref = None

        if reuse_existing:
            # Try to find an already running node we can reuse
            ns = namespace.strip("/")
            fullname = "/" + ns + ("/" if ns else "") + name

            # Check if it's a node we've created
            node_ref = self.query_node(fullname, include_components=False)

            if not node_ref:
                # Otherwise see if there's a foreign node matching the full name
                living_nodes = set(
                    _ns + ("" if _ns.endswith("/") else "/") + _name
                    for _name, _ns in self.shared_node.get_node_names_and_namespaces()
                )

                if fullname in living_nodes:
                    node_processes = find_process_for_node(namespace, name)
                    if not node_processes:
                        self.logger.error(
                            "Could not identify process for node %s/%s, creating new composer",
                            namespace,
                            name,
                        )
                    elif len(node_processes) > 1:
                        self.logger.warning(
                            "Found multiple node processes matching %s/%s, using most recent",
                            namespace,
                            name,
                        )
                        node_ref = ForeignNode.wrap_process(node_processes[-1])
                    else:
                        node_ref = ForeignNode.wrap_process(node_processes[0])

        if node_ref and not Composer.is_composer(node_ref, timeout=ros_waittime):
            # We will still reuse it but raise some awareness
            self.logger.warning(
                f"Reused composer node {node_ref.fullname} does not provide the expected services (yet)"
            )

        if not node_ref:
            # Node doesn't exist yet or it should not be reused, create a new composer
            package = f"rcl{language}_components"

            # The actual implementation of the composer
            if variant == "normal":
                executable = "component_container"
            elif variant == "multithreading":
                executable = "component_container_mt"
            elif variant == "isolated":
                executable = "component_container_isolated"
            else:
                raise ValueError(f"Unknown container mode '{variant}")

            node_ref = Node(package, executable, name, namespace, remaps=component_remaps, output=output)

        if isinstance(node_ref, Composer):
            comp = node_ref
        else:
            comp = Composer(node_ref, component_remaps=component_remaps, output=output)

        try:
            group.add_node(comp)

            if autostart_process:
                comp.start(service_timeout=ros_waittime)

            self._composition_node = comp
            yield comp
        finally:
            self._composition_node = None

    def component(
        self,
        package: str,
        plugin: str,
        name: str = None,
        *,
        remaps: dict[str, str] = None,
        params: str | dict[str, Any] = None,
        anonymous: bool = False,
        hidden: bool = False,
        use_intra_process_comms: bool = True,
        ros_waittime: float = 3.0,
        lifecycle_waittime: float = 0.01,
        lifecycle_target: LifecycleStage = LifecycleStage.ACTIVE,
        output: LogSink | set[LogSink] = "screen",
        **extra_composer_args: dict[str, Any],
    ) -> Component:
        """Create a component and load it into an existing :py:meth:`compose` context.

        If you instead want to load components without a `compose` context, you should instantiate :py:class:`Component` objects directly, then load them via :py:meth:`Component.start` or :py:meth:`Composer.load_component`. See the examples for more details.

        Parameters
        ----------
        package : str
            The package providing the component implementation.
        plugin : str
            The name the component is registered as, typically of the form `<package>::<Name>`.
        name : str, optional
            The name the instantiated component should be known as. If `None`, a name will be derived from `package` and `plugin`, and `anonymous` will be set to True.
        remaps : dict[str, str], optional
            Tells the node to replace any topics it wants to interact with according to the provided dict.
        anonymous : bool, optional
            If True, the composer name will be appended with a unique suffix to avoid name conflicts.
        hidden : bool, optional
            If True, the composer name will be prepended with a "_", hiding it from common listings.
        params : str | dict[str, Any], optional
            Any ROS parameters you want to pass to the component. These are the args you would typically have to declare in your launch file. A string will be interpreted as a path to a yaml file which will be lazy loaded using :py:meth:`BetterLaunch.load_params`.
        use_intra_process_comms : bool, optional
            If True, ask the composer node to enable intra-process communication, i.e. share memory between components when passing messages instead of serializing and deserializing.
        ros_waittime : float, optional
            How long to wait for the component to register with ROS. This should cover the time between the process starting and the component initializing itself. Set negative to wait indefinitely. Set to None to avoid the check entirely. Will do nothing if `autostart_process` is False.
        lifecycle_waittime : float, optional
            How long to wait for the component's lifecycle management to come up. This should cover the time between the component initializing itself (see `ros_waittime`) and creating its additional topics and services. While neglible on modern computers, slower devices and embedded systems may experience a noticable delay here. Set negative to wait indefinitely. Set to None to avoid the check entirely. Will do nothing if `autostart_process` is False.
        lifecycle_target : LifecycleStage, optional
            The lifecycle stage to bring the component into after starting. Has no effect if `autostart_process` is False or if the component does not appear to be a lifecycle component after waiting `ros_waittime + lifecycle_waittime`.
        output : LogSink | set[LogSink], optional
            Determines if and where this node's output should be directed. Common choices are `screen` to print to terminal, `log` to write to a common log file, `own_log` to write to a node-specific log file, and `none` to not write any output anywhere. See :py:meth:`configure_logger` for details.

        Returns
        -------
        Component
            The component that has been loaded into the current :py:meth:`compose` context.

        Raises
        ------
        RuntimeError
            If this is called outside a :py:meth:`compose` context.
        """
        if self._composition_node is None:
            raise RuntimeError("Cannot add component outside a compose() node")

        if not name:
            name = f"{package}_{plugin.replace('::', '_')}"
            anonymous = True

        if anonymous:
            name = self.get_unique_name(name)

        if hidden and not name.startswith("_"):
            name = "_" + name

        group = self.group_tip
        namespace = group.assemble_namespace()

        comp = Component(
            self._composition_node,
            package,
            plugin,
            name,
            namespace,
            remaps=remaps,
            params=params,
            output=output,
        )

        # Equivalent to self._composition_node.load_component(comp)
        comp.start(
            use_intra_process_comms=use_intra_process_comms,
            **extra_composer_args,
        )

        if ros_waittime is not None and comp.is_ros2_connected(ros_waittime):
            if (
                lifecycle_target not in (None, LifecycleStage.PRISTINE)
                and lifecycle_waittime is not None
                and comp.is_lifecycle_node(lifecycle_waittime)
            ):
                comp.lifecycle.transition(lifecycle_target)

        return comp

    def include(
        self,
        package: str,
        launchfile: str,
        subdir: str = None,
        *,
        pass_launch_func_args: bool = True,
        **kwargs,
    ) -> None:
        """Include another launch file, resolving its path using :py:meth:`find`.

        The file is first read into memory and checked. If it seems to be a *better_launch* launch file, it is executed immediately (using :py:func:`exec`). The BetterLaunch instance and global context will be shared. Any arguments to :py:meth:`launch_this` in the included launch file will be ignored.

        If the file does not appear to be a *better_launch* launch file, it is assumed to be a regular ROS2 launch file. In this case a :py:class:`launch.actions.IncludeLaunchDescription` instance is created and passed to :py:meth:`ros2_actions`.

        Parameters
        ----------
        package : str
            The package containing the specified launch file. May be `None` (see :py:meth:`find`).
        launchfile : str
            The name of a launch file to execute.
        subdir : str, optional
            A path fragment the launch file must be located in.
        pass_launch_func_args : bool, optional
            If True, all :py:meth:`launch_args` will be passed to the included launch file. Additional launch arguments can also be provided via the `kwargs`.

        Raises
        ------
        ValueError
            If the passed in `search_args` cannot be handled.
        """
        file_path = self.find(package, launchfile, subdir)

        # Pass additional arguments, e.g. launch args
        include_args = {}
        if pass_launch_func_args:
            include_args.update(self.launch_args)
        include_args.update(**kwargs)

        if find_launchthis_function(file_path):
            try:
                with open(file_path) as f:
                    source = f.read()
                    
                code = compile(source, launchfile, "exec")

                # Make sure the included launch file reuses our BetterLaunch instance
                global_args = dict(globals())
                global_args[_bl_singleton_instance] = self
                global_args[_bl_include_args] = include_args

                # Since we're running an entire module locals won't have any effect
                exec(code, global_args)
            except Exception as e:
                self.logger.error(
                    f"Launch include '{package}/{launchfile}' failed: {e}"
                )
                raise
        else:
            # Was not a better_launch launch file, assume it's a ROS2 launch file (py, xml, yaml)
            self._include_ros2_launchfile(file_path, **include_args)

    def _include_ros2_launchfile(self, file_path, **kwargs) -> None:
        # Delegate to ros2 launch service
        from launch.actions import IncludeLaunchDescription
        from launch.launch_description_sources import (
            AnyLaunchDescriptionSource,
        )

        # See https://github.com/ros2/launch_ros/blob/rolling/ros2launch/ros2launch/api/api.py#L175
        ros2_include = IncludeLaunchDescription(
            AnyLaunchDescriptionSource(file_path),
            launch_arguments=[
                # ROS2 can handle only tuples of strings and strings/substitutions here...
                (key, str(val) if val is not None else "")
                for key, val in kwargs.items()
            ],
        )
        self.ros2_actions(ros2_include)

    def ros2_launch_service(
        self,
        name: str = "LaunchService",
        launchservice_args: list[str] = None,
        output: LogSink | set[LogSink] = "screen",
        start_immediately: bool = True,
    ) -> Ros2LaunchWrapper:
        """Create or retrieve a manager object that can be used for queueing ROS2 launch actions.

        Usually, calling :py:meth:`ros2_actions` is more convenient for queueing actions. However, calling this *first* allows to prevent starting the underlying :py:class:`launch.LaunchService` immediately, giving more control over when the actions are executed.

        Since the `LaunchService` insists on running on the main thread it will be started as a sub process.

        Note that only one instance of the ROS2 wrapper should ever exist. Calling this method after it has been created will return the already existing instance instead. Any passed arguments will be silently discarded.

        Parameters
        ----------
        name : str, optional
            The name used to identify the process and its logger.
        launchservice_args : list[str], optional
            Additional launch arguments to pass to the ROS2 launch service. These will end up in :py:meth:`launch.LaunchContext.argv`.
        output : LogSink  |  set[LogSink], optional
            How log output from the launch service should be handled. This will also include the output from all nodes launched by this launch service. Common choices are `screen` to print to terminal, `log` to write to a common log file, `own_log` to write to a node-specific log file, and `none` to not write any output anywhere. See :py:meth:`configure_logger` for details.
        start_immediately : bool, optional
            If True, the ROS2 launch service process is started immediately.

        Returns
        -------
        Ros2LaunchWrapper
            The wrapper hosting the ROS2 launch service process.
        """
        if not self._ros2_launcher:
            self._ros2_launcher = Ros2LaunchWrapper(
                name=name,
                launchservice_args=launchservice_args,
                output=output,
            )

        if start_immediately:
            self._ros2_launcher.start()

        return self._ros2_launcher

    def ros2_actions(self, *ros2_actions) -> Ros2LaunchWrapper:
        """Submit additional ROS2 launch actions for execution.

        If no :py:class:`launch.LaunchService` exists yet it will be created and started immediately.
        """
        self.ros2_launch_service().queue_ros2_actions(*ros2_actions)
        return self._ros2_launcher

    def run_later(self, delay: float, callback: Callable, *args, **kwargs) -> Future:
        """Convenience method for running a callback with a delay. The callback will be called on a separte thread.

        This mainly exists to cover the use case where you want to interact with ROS from an `rclpy.Timer`. A synchronous call from within a timer (e.g. a service call like :py:meth:`Node.set_live_params`) will block ROS' background event loop, preventing publishers, subscribers, services, etc. from doing their work. It will also prevent a clean shutdown as ROS usually waits for the event queue to become empty.

        When executing a long running task this way it is a good idea to check :py:meth:`is_shutdown` in between iterations.

        Parameters
        ----------
        delay : float
            How long to wait in seconds before calling the callback.
        callback : Callable
            The function to call after the timeout. Will not be called if :py:meth:`shutdown` is called beforehand.
        *args : Any, optional
            Positional arguments to the callback.
        **kwargs : Any, optional
            Keyword arguments to the callback.

        Returns
        -------
        Future
            A future which will be cancelled on `shutdown`, otherwise it will hold the callback's result or an exception the callback raised.
        """
        future = Future()

        def run():
            time.sleep(delay)

            if future.cancelled():
                return

            if self.is_shutdown:
                future.cancel()
                return

            try:
                ret = callback(*args, **kwargs)
                future.set_result(ret)
            except Exception as e:
                future.set_exception(e)

        # TODO this is a good candidate for running on an asyncio loop
        threading.Thread(target=run, daemon=True).start()
        return future
