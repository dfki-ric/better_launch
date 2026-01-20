from typing import Any, Iterable
import os
import time
import psutil
import signal
import logging
from fnmatch import fnmatch
import re
import json
import threading
from xml.etree import ElementTree

from ament_index_python.packages import get_packages_with_prefixes

from better_launch.utils.better_logging import LogSink
from .abstract_node import AbstractNode
from .node import Node
from .live_params_mixin import LiveParamsMixin
from .lifecycle_manager import LifecycleStage


def find_ros2_node_processes() -> list[psutil.Process]:
    """Finds processes that seem to be ROS2 nodes.

    Unfortunately, ROS2 doesn't provide any means of discovering node internals other than by looking at the process command line. Lucky for us, there are a couple of distinct command line arguments that are somewhat unique to ROS. These are:
    - --ros-args for passing arguments
    - __ns:=<namespace>
    - __node:=<name>
    - __name:=<name>

    If any of these are present, the process will be added to the returned list.

    Returns
    -------
    list[psutil.Process]
        The processes that appear to be ROS2 nodes.
    """
    # NOTE we won't be able to discover nodes started by ros2 run this way, but there's really
    # nothing distinctive about those, e.g.:
    #
    # /usr/bin/python3 /opt/ros/humble/bin/ros2 run examples_rclpy_minimal_publisher publisher_local_function
    # /usr/bin/python3 /opt/ros/humble/lib/examples_rclpy_minimal_publisher/publisher_local_function
    ret = []

    for p in psutil.process_iter():
        try:
            cmd = p.cmdline()
            if p.is_running() and (
                "--ros-args" in cmd
                or "__ns:=" in cmd
                or "__node:=" in cmd
                or "__name:=" in cmd
            ):
                ret.append(p)
        except psutil.ZombieProcess:
            pass

    return ret


def find_process_for_node(namespace: str, name: str) -> list[psutil.Process]:
    """Find processes that look like ROS2 nodes which have been passed the specified namespace and name.

    Parameters
    ----------
    namespace : str
        The namespace to look for.
    name : str
        The node name to look for.

    Returns
    -------
    list[psutil.Process]
        A list processes that match the above criteria.
    """
    r_pkg = re.compile(rf"__ns:={namespace}")
    r_name = re.compile(rf"__(?:node|name):={name}")

    candidates = []

    for p in psutil.process_iter():
        pkg_match = False
        name_match = False

        try:
            cmd = p.cmdline()
            for arg in cmd:
                if r_pkg.match(arg):
                    pkg_match = True
                elif r_name.match(arg):
                    name_match = True

                if pkg_match and name_match:
                    candidates.append(p)
                    break
        except psutil.ZombieProcess:
            pass

    return candidates


def get_package_for_path(path: str) -> tuple[str, str]:
    """Find the ROS2 package associated with the specified path.

    This will first check the currently registered packages (which are stored in `$AMENT_PREFIX_PATH`). If none of these match it will search through the path starting from the end for a valid `package.xml` file to get the package name.

    Parameters
    ----------
    path : str
        An absolute path to find the package for.

    Returns
    -------
    tuple[str, str]
        The package name and path to the package, or (None, None) if the package could not be determined.
    """
    path = os.path.normpath(os.path.abspath(os.path.dirname(path)))
    ros_packages = get_packages_with_prefixes()

    for pkg, pkg_path in ros_packages.items():
        # Try to find the package in the currently registered packages
        if path.startswith(pkg_path):
            return pkg, pkg_path
    else:
        # Not a package currently sourced, look for a package.xml somewhere on the path. This search
        # is somewhat expensive, but we expect it to be rare since usually packages should already
        # be sourced 99.9% of the time
        while os.path.sep in path:
            # The package.xml is usually found in install/<package>/share/<package>
            package_candidate = os.path.basename(path)
            candidates = [
                os.path.join("share", package_candidate, "package.xml"),
                "package.xml",
            ]

            for package_xml in candidates:
                if os.path.isfile(package_xml):
                    # Unfortunately the package name can be different from the package's folder, so
                    # we get it from the package.xml instead
                    tree = ElementTree.parse(package_xml)
                    root = tree.getroot()
                    if root.tag != "package":
                        # Not an actual package file
                        continue

                    name_tag = root.find("name")
                    if name_tag:
                        # Found it!
                        return name_tag.text, path

            # Go up one level
            path = path.rsplit(os.path.sep, maxsplit=1)[0]

    return None, None


def parse_process_args(
    process: psutil.Process, node: AbstractNode = None
) -> tuple[str, str, dict[str, str], dict[str, str], list[str]]:
    """Parse ROS2 command line arguments and return the user-specified parts.

    In particular, this will return the passed ROS2 params, remaps and additional command line arguments. Special ROS2 arguments like `--ros-args`, `--remap`, etc. will not be included. A node may be passed in order to resolve `nodename:key:=value` style args and load parameter files from `--params-file`.

    Parameters
    ----------
    cmd_args : list[str]
        The command line arguments to parse, including the call to the executable at [0].
    node : AbstractNode, optional
        A node to use when resolving additional details.

    Returns
    -------
    tuple[dict[str, str], dict[str, str], list[str]]
        The node's namespace and name, followed by its ROS2 params, remaps and additional command line args.
    """
    from better_launch import BetterLaunch

    node_name = ""
    namespace = ""
    params = {}
    remaps = {}
    additional_args = []
    is_ros_args = False
    skip = 1

    cmd_args = process.cmdline()
    bl = BetterLaunch.instance()

    for i, arg in enumerate(cmd_args):
        if skip > 0:
            # Skip the executable and args we already parsed
            skip -= 1
            continue

        if arg == "--ros-args":
            is_ros_args = True
            continue

        if is_ros_args:
            if arg in ["-p", "--param"]:
                skip = 1
                key, val = cmd_args[i + 1].split(":=")
                params[key] = val

            elif arg in ["-r", "--remap"]:
                skip = 1
                key, val = cmd_args[i + 1].split(":=")
                if key == "__ns":
                    namespace = val
                elif key in ["__name", "__node"]:
                    node_name = val
                elif ":" in key:
                    # ROS2 supports a pattern where the key is preceded by the
                    # node's name to make node-specific remaps for e.g. components
                    qualifier, key = key.split(":", maxsplit=1)
                    # TODO if we have the node we don't need the node name...?
                    if node:
                        if qualifier != node.name and not fnmatch(node.fullname, qualifier):
                            continue

                    # NOTE: an especially unhinged developer could write a node process creating
                    # multiple nodes and then start them like
                    #
                    #   -r __name:=X -r node1:__name:=Y -r node2:__name:=Z ...
                    #
                    # In this case we will get multiple matches here unless we have a node name to
                    # look for. Even if there is an unqualified __ns or __name we cannot tell if 
                    # it is overridden by a more specific remap rule unless we know the original 
                    # node name.
                    if key == "__ns":
                        if namespace and not node:
                            logging.getLogger().warning(
                                f"Node process {process.pid} has ambivalent namespace arguments: {cmd_args}"
                            )
                        namespace = val
                    elif key in ["__name", "__node"]:
                        if node_name and not node:
                            logging.getLogger().warning(
                                f"Node process {process.pid} has ambivalent node name arguments: {cmd_args}"
                            )
                        node_name = val
                    else:
                        remaps[key] = val

            elif arg == "--params-file":
                skip = 1
                param_file = cmd_args[i + 1]
                params.update(bl.load_params(None, param_file, qualifier=node))

            else:
                # No special handling
                bl.logger.warning("parse_process_args: unhandled ros-arg %s", arg)
        else:
            # Nothing we handle, assume it's a regular command line arg
            additional_args.append(arg)

    return namespace, node_name, params, remaps, additional_args


def find_foreign_nodes() -> list[AbstractNode]:
    """Searches the running processes for ROS2 nodes that have not been started by this *better_launch* process and wraps them in ForeignNode instances.

    Returns
    -------
    list[AbstractNode]
        A list of discovered foreign ROS2 nodes.
    """
    from better_launch import BetterLaunch

    bl = BetterLaunch.instance()

    # bl.query_node would iterate over all nodes every time
    my_nodes = {
        n.fullname
        for n in bl.get_nodes(
            include_components=True, include_launch_service=False, include_foreign=False
        )
    }
    
    foreign = []
    for p in find_ros2_node_processes():
        try:
            foreign.append(ForeignNode.wrap_process(p))
        except Exception as e:
            bl.logger.debug(f"Could not create foreign node: {e}", exc_info=True)

    return filter(lambda n: n.fullname not in my_nodes, foreign)


class ForeignNode(AbstractNode, LiveParamsMixin):
    @classmethod
    def wrap_process(cls, process: psutil.Process) -> "ForeignNode":
        """Collect information like namespace, package, executable and so on from a process and wrap it in a ForeignNode instance.

        Note that there is no way to verify whether the process actually belongs to a ROS node. Consider using e.g. :py:meth:`find_ros2_node_processes` to that effect.

        Parameters
        ----------
        process : psutil.Process
            The process to wrap.

        Returns
        -------
        ForeignNode
            A node object carrying the extracted node information.
        """
        from better_launch import BetterLaunch

        bl = BetterLaunch.instance()

        namespace, name, params, remaps, additional_args = parse_process_args(process)
        exec_dir = os.path.dirname(process.cmdline()[0])
        package, _ = get_package_for_path(exec_dir)

        if not namespace:
            bl.logger.warning("Process did not specify a node namespace")

        if not name:
            bl.logger.warning("Process did not specify a node name")

        return ForeignNode(
            process,
            package,
            name,
            namespace,
            remaps=remaps,
            params=params,
            cmd_args=additional_args,
        )

    def __init__(
        self,
        process: psutil.Process,
        package: str,
        name: str,
        namespace: str,
        *,
        remaps: dict[str, str] = None,
        params: str | dict[str, Any] = None,
        cmd_args: list[str] = None,
        output: LogSink | Iterable[LogSink] | Iterable[str] | str = LogSink.SCREEN,
    ):
        """This class is used for representing nodes not managed by this better_launch process.

        Although ROS2 has no mechanism to retrieve e.g. the package name from a running node, most information can be retrieved from the process object itself.

        In general, you should probably use :py:meth:`ForeignNode.wrap_process` instead of instantiating this class directly.

        Parameters
        ----------
        process : psutil.Process
            A reference to the running node's process.
        package : str
            The package providing the node.
        name : str
            This node's name. If it is a ROS node it should be how the node registers with ROS.
        namespace : str
            The node's namespace. Must be absolute, i.e. start with a '/'.
        remaps : dict[str, str], optional
            Tells the node to replace any topics it wants to interact with according to the provided dict.
        params : str | dict[str, Any], optional
            Any arguments you want to provide to the node. These are the args you would typically have to declare in your launch file. A string will be interpreted as a path to a yaml file which will be lazy loaded using :py:meth:`BetterLaunch.load_params`.
        cmd_args : list[str], optional
            Additional command line arguments to pass to the node.
        output : LogSink | Iterable[LogSink] | Iterable[str] | str, optional
            Determines if and where this node's output should be directed. *Note* however that this only applies to output generated by THIS process, not the node's output. To properly capture the node output you must call :py:meth:`ForeignNode.takeover` first.
        """
        super().__init__(
            package,
            process.cmdline()[0],
            name,
            namespace,
            remaps=remaps,
            params=params,
            output=output,
        )

        self._process = process
        self._cmd_args = cmd_args

        # Watch the process and notify user when it terminates
        self._watch_process()

    @property
    def pid(self) -> int:
        """The process ID of the node process. Will be -1 if the process is not running."""
        if not self.is_running:
            return -1
        return self._process.pid

    @property
    def cmd_args(self) -> list[str]:
        """Additional arguments passed to the node process."""
        return self._cmd_args

    @property
    def is_running(self) -> bool:
        return self._process and self._process.is_running()

    def join(self, timeout: float = None) -> int:
        """Wait for the underlying process to terminate and return its exit code. Returns immediately if the process is not running.

        Parameters
        ----------
        timeout : float, optional
            How long to wait for the process to finish. Wait forever if None.

        Returns
        -------
        int
            The exit code of the process, or None if it is already terminated.

        Raises
        ------
        TimeoutError
            If a timeout was specified and the process is still running by the time the timeout expires.
        """
        proc = self._process
        if proc:
            try:
                # Seems to work here despite setpgrp?
                return proc.wait(timeout)
            except psutil.TimeoutExpired as e:
                raise TimeoutError from e

    def start(self) -> None:
        """Usually a foreign node will already be running upon construction. However, this method can be used when restarting the process after it has terminated.
        
        See also :py:meth:`takeover`.
        """
        from better_launch import BetterLaunch

        bl = BetterLaunch.instance()
        if bl.is_shutdown:
            self.logger.warning(
                f"Node {self} will not be started as the launcher has already shut down"
            )
            return

        if self.is_running:
            self.logger.warning(f"Node {self} is already started")
            return

        final_cmd = [self.executable] + self.cmd_args + ["--ros-args"]

        # Attach node parameters
        for key, value in self._flat_params().items():
            # Make sure the values are parseable for ROS
            final_cmd.extend(["-p", f"{key}:={json.dumps(value)}"])

        # Special args and remaps
        # launch_ros/actions/node.py:206
        for src, dst in self._ros_args().items():
            # launch_ros/actions/node.py:481
            final_cmd.extend(["-r", f"{src}:={dst}"])

        self.logger.info(f"Starting process '{' '.join(final_cmd)}'")

        # Start the node process
        # NOTE it is very difficult if not impossible to capture a process' output if we did not
        # set it up ourselves. The clean way is to terminate the process and restart it from this
        # process. See the takeover function below which does precisely that.
        self._process = psutil.Popen(
            final_cmd,
            cwd=None,
            shell=False,
            text=True,
            preexec_fn=os.setpgrp,  # start in separate process group
        )

        # Watch the process and notify user when it terminates
        self._watch_process()

    def _watch_process(self) -> None:
        # TODO Capture process output!
        # To capture output we can use `strace -p1234 -s9999 -e write` where 1234 is the process
        # pid. However, this requires sudo rights unless we got the "cap_sys_ptrace+ep" capability
        # granted. This can only be granted to binary programs, not to python scripts, so we'd have
        # to create a small C++ binary (bl?). Alternatively we need to request sudo permissions,
        # but the input line might get swepped away by other node logs...

        def wait():
            ret = self.join()

            if ret is None:
                self.logger.warning("Process has already finished")
            elif ret == 0:
                self.logger.warning("Process has finished cleanly")
            else:
                self.logger.critical(f"Process has died with exit code {ret}")

        # TODO this is probably a great use case for asyncio
        threading.Thread(target=wait, daemon=True).start()

    def shutdown(
        self, reason: str, signum: int = signal.SIGTERM, timeout: float = 0.0
    ) -> None:
        if not self.is_running:
            return

        signame = signal.Signals(signum).name

        if signum == signal.SIGTERM and self._lifecycle_manager:
            try:
                self._lifecycle_manager.transition(LifecycleStage.FINALIZED)
            except Exception as e:
                self.logger.warning(f"Lifecycle transition to FINALIZED failed: {e}")

        self.logger.warning(
            f"Forwarding shutdown signal to foreign process: {reason} ({signame})"
        )
        self._process.send_signal(signum)

        if timeout == 0.0:
            return

        try:
            self._process.wait(timeout)
        except psutil.TimeoutExpired:
            raise TimeoutError("Node did not shutdown within the specified timeout")

    def takeover(self, kill_after: float = 0, **node_args) -> Node:
        """Replaces a foreign node with a node belonging to this better_launch process. This allows
        to e.g. capture the node's output and control a few additional runtime parameters. Any
        interactions with this foreign node instance after this function returns are undefined
        behavior.

        **NOTE:** Currently the only way to takeover a node is to stop the original process, then
        recreate and restart the node with the same arguments as the original node.

        Parameters
        ----------
        kill_after: float, optional
            Kill the node process if it takes longer than this many seconds to shutdown. Disabled when <= 0.
        node_args : dict[str, Any], optional
            Additional arguments to pass to the node. See :py:class:`Node` for additional details.

        Returns
        -------
        Node
            The new node instance that should replace this foreign node.
        """
        from better_launch import BetterLaunch

        start = time.time()
        self.shutdown("Taking over node")

        while True:
            if self.is_running:
                break

            time.sleep(0.1)
            now = time.time()

            if kill_after > 0 and now - start > kill_after:
                self._process.kill()
                break

        self.logger.info("Old process has terminated, restarting node")
        node = Node(
            self.package,
            self.executable,
            self.name,
            self.namespace,
            remaps=self.remaps,
            params=self.params,
            cmd_args=self.cmd_args,
            **node_args,
        )

        bl = BetterLaunch.instance()
        g = bl.find_group_for_namespace(self.namespace, True)
        g.add_node(node)

        node.start()

        # This ForeignNode instance should not be used anymore
        self._process = None

        return node

    def _get_info_section_general(self):
        info = super()._get_info_section_general()
        return (
            info
            + f"""
\x1b[1mProcess\x1b[0m
  PID:       {self.pid}
  Cmd Args:  {self.cmd_args}
"""
        )
