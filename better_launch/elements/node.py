from typing import Any, Callable, Iterable
import os
import platform
import signal
import traceback
import time
import re
import logging
import threading
import subprocess
import queue
from pprint import pformat
import json
import shlex

from better_launch.utils.better_logging import LogSink, ROSLOG_PATTERN_BL
from .abstract_node import AbstractNode
from .live_params_mixin import LiveParamsMixin
from .lifecycle_manager import LifecycleStage


class Node(AbstractNode, LiveParamsMixin):
    def __init__(
        self,
        package: str,
        executable: str,
        name: str,
        namespace: str,
        *,
        remaps: dict[str, str] = None,
        params: str | dict[str, Any] = None,
        param_files: str | list[str] = None,
        use_sim_time: bool = False,
        drop_param_qualifiers: bool = False,
        cmd_args: str | list[str] = None,
        prefix_args: str | list[str] = None,
        env: dict[str, str] = None,
        isolate_env: bool = False,
        log_level: int = logging.INFO,
        output: LogSink | Iterable[LogSink] | Iterable[str] | str = LogSink.SCREEN,
        on_exit: Callable = None,
        max_respawns: int = 0,
        respawn_delay: float = 0.0,
        use_shell: bool = False,
        raw: bool = False,
        remap_qualifier: str = None,
        qualify_all_remaps: bool = False,
    ):
        """An object used for starting a ROS node and capturing its output.

        Parameters
        ----------
        package : str
            The package providing the node.
        executable : str
            The executable that should be run.
        name : str, optional
            The name you want the node to be known as.
        namespace : str
            The node's namespace. Must be absolute, i.e. start with a '/'.
        remaps : dict[str, str], optional
            Tells the node to replace any topics it wants to interact with according to the provided dict.
        params : str | dict[str, Any], optional
            Any arguments you want to provide to the node. These are the args you would typically have to declare in your launch file. A string will be interpreted as a path to a yaml file which will be lazy loaded using [BetterLaunch.load_params][].
        param_files : str | list[str], optional
            Paths to parameter files that will be passed to the node as is. If both param_files and params are present, param_files will be passed first (same order), followed by the params.
        drop_param_qualifiers : bool, optional
            If True, any namespace/node qualifiers in the passed params are ignored.
        cmd_args : str | list[str], optional
            Additional command line arguments to pass to the node. If a string is passed it will be split using shlex.
        prefix_args : str | list[str], optional
            Arguments to prepend to the resolved run command, e.g. for executing the node through gdb. If a string is passed it will be split using shlex.
        env : dict[str, str], optional
            Additional environment variables to set for the node's process. The node process will merge these with the environment variables of the better_launch host process unless `isolate_env` is True.
        isolate_env : bool, optional
            If True, the node process' env will not be inherited from the parent process and only those passed via `env` will be used. Be aware that this can result in many common things to not work anymore since e.g. keys like *PATH* will be missing.
        log_level : int, optional
            The minimum severity a logged message from this node must have in order to be published. This will be added to the cmd_args unless it is None.
        output : LogSink | Iterable[LogSink] | Iterable[str] | str, optional
            Determines if and where this node's output should be directed. Common choices are `screen` to print to terminal, `log` to write to a common log file, `own_log` to write to a node-specific log file, and `none` to not write any output anywhere. See [configure_logger][utils.better_logging.configure_logger] for details.
        on_exit : Callable, optional
            A function to call when the node's process terminates (after any possible respawns).
        max_respawns : int, optional
            How often to restart the node process if it terminates.
        respawn_delay : float, optional
            How long to wait before restarting the node process after it terminates.
        use_shell : bool, optional
            If True, invoke the node executable via the system shell. While this gives access to the shell's builtins, this has the downside of running the node inside a "mystery program" which is platform and user dependent. Generally not advised.
        raw : bool, optional
            If True, don't treat the executable as a ROS2 node and avoid passing it any command line arguments except those specified.
        remap_qualifier : str, optional
            Additional qualifier that will precede the node's `__ns` and `__name` remap rules. Should be the original name of the node (i.e. whatever its default name is) and can be qualified with a namespace. Useful to prevent multiple nodes with the same name when a process can have more than one node (e.g. `controller_manager`). See `this ROS2 design doc <https://design.ros2.org/articles/static_remapping.html#how-the-syntax-works`_ for more information.
        qualify_all_remaps : bool, optional
            If True, apply the `remap_qualifier` to all remaps that are not already qualified.
        """
        super().__init__(
            package,
            executable,
            name,
            namespace,
            remaps,
            params,
            param_files,
            output=output,
        )

        if isinstance(cmd_args, str):
            cmd_args = shlex.split(cmd_args)

        if isinstance(prefix_args, str):
            prefix_args = shlex.split(prefix_args)

        self.use_sim_time = use_sim_time
        self.drop_param_qualifiers = drop_param_qualifiers
        self.prefix_args = prefix_args or []
        self.cmd_args = cmd_args or []
        self.env = env or {}
        self.isolate_env = isolate_env
        self.node_log_level = (
            logging.getLevelName(log_level) if isinstance(log_level, int) else log_level
        )
        self.use_shell = use_shell
        self.max_respawns = max_respawns
        self.respawn_delay = respawn_delay
        self._respawn_retries = 0
        self._process: subprocess.Popen = None
        self._on_exit_callback = on_exit
        self.raw = raw
        self.remap_qualifier = remap_qualifier
        self.qualify_all_remaps = qualify_all_remaps

    @property
    def pid(self) -> int:
        """The process ID of the node process. Will be -1 if the process is not running."""
        if not self.is_running:
            return -1
        return self._process.pid

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

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
            except subprocess.TimeoutExpired as e:
                raise TimeoutError from e

    def start(self) -> None:
        from better_launch import BetterLaunch

        launcher = BetterLaunch.instance()
        if launcher.is_shutdown:
            self.logger.warning(
                f"Node {self} will not be started as the launcher has already shut down"
            )
            return

        if self.is_running:
            self.logger.warning(f"Node {self} is already started")
            return

        try:
            cmd = launcher.find(f"{self.package}/lib", self.executable)

            final_cmd = self.prefix_args + [cmd]
            if self.cmd_args:
                final_cmd.extend(self.cmd_args)

            if not self.raw:
                final_cmd += ["--ros-args"]

                if self.node_log_level is not None:
                    final_cmd += ["--log-level", self.node_log_level]

                # Special args and remaps
                # https://github.com/ros2/launch_ros/blob/rolling/launch_ros/launch_ros/actions/node.py

                # Qualifier to create node-specific remaps
                qualifier = ""
                if self.remap_qualifier:
                    qualifier = self.remap_qualifier
                    if not qualifier.endswith(":"):
                        qualifier += ":"

                # Why do I hear mad hatter music???
                # See https://docs.ros.org/en/jazzy/How-To-Guides/Node-arguments.html
                remaps = {}
                if self.namespace:
                    remaps["__ns"] = self.namespace
                if self.name:
                    remaps["__node"] = self.name
                remaps.update(self.remaps)

                for src, dst in remaps.items():
                    if qualifier:
                        if src in ("__ns", "__node", "__name"):
                            src = qualifier + src
                        elif self.qualify_all_remaps and ":" not in src:
                            src = qualifier + src

                    final_cmd.extend(["-r", f"{src}:={dst}"])

                # Pass param files first
                for path in self.param_files:
                    final_cmd.extend(["--params-file", path])

                # Attach node parameters

                # TODO I could not find a way to pass a qualified param to a namespaced node yet.
                # See https://github.com/ros2/rcl/issues/1306
                drop_qualifiers = self.drop_param_qualifiers
                if len(self.namespace) > 1:
                    drop_qualifiers = True
                    self.logger.debug(
                        "Qualified params cannot be passed to namespaced nodes and will be passed unqualified instead"
                    )

                if self.use_sim_time:
                    final_cmd.extend(["-p", "use_sim_time:=true"])

                for key, value in self._flat_params(drop_qualifiers).items():
                    # Make sure the values are parseable for ROS
                    final_cmd.extend(["-p", f"{key}:={json.dumps(value)}"])

            # If an env is specified ROS2 lets it completely replace the host env. We cover this
            # through an additional flag, as often you just want to make certain overrides.
            # https://github.com/ros2/launch/blob/rolling/launch/launch/descriptions/executable.py
            if self.isolate_env:
                final_env = self.env
            else:
                final_env = dict(os.environ) | self.env

            # All args must be strings
            final_cmd = [str(s) for s in final_cmd]

            print_cmd = final_cmd
            # for s in final_cmd[1:]:
            #     if len(s) > 50:
            #         s = s[:50] + "..."
            #     i = s.find("\n")
            #     if i > 0:
            #         s = s[:i] + "..."
            #     print_cmd.append(s)

            env_str = pformat(self.env, compact=True)
            self.logger.info(f"Starting process '{' '.join(print_cmd)}', env={env_str}")

            # Start the node process
            self._process = subprocess.Popen(
                final_cmd,
                cwd=None,
                env=final_env,
                shell=self.use_shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                # start in separate process group so it doesn't react to our sigint immediately
                preexec_fn=os.setpgrp,
            )

            # Watch the process for output and react when it terminates
            threading.Thread(
                target=self._watch_process,
                args=[self._process],
                daemon=True,
            ).start()

        except Exception:
            self.logger.error(
                f"An exception occurred while executing process:\n{traceback.format_exc()}"
            )

    def _watch_process(
        self,
        process: subprocess.Popen,
    ) -> None:
        # Non-blocking reads might miss some output, so we use blocking reads in
        # separate threads instead
        stdout_queue = queue.Queue()
        stderr_queue = queue.Queue()

        # Same pattern as what our PrettyLogFormatter is looking for
        ros_message_pattern = re.compile(ROSLOG_PATTERN_BL)

        def read_stream(stream, q):
            try:
                while True:
                    line = stream.readline()
                    if not line:  # EOF
                        break
                    q.put(line.rstrip("\n\r"))
            except Exception:
                # Signal error/EOF
                q.put(None)

        def collect_bundle(q):
            nonlocal active_streams
            try:
                line = q.get(timeout=0.1)
                if line is None:
                    active_streams -= 1
                    return

                # Collect any additional lines that arrive immediately
                bundle = [line]
                while True:
                    try:
                        # Very short timeout to check for more lines
                        next_line = q.get(timeout=0.01)
                        if next_line is None:  # EOF
                            active_streams -= 1
                            break

                        bundle.append(next_line)
                    except queue.Empty:
                        # No more lines immediately available
                        break

                return bundle
            except queue.Empty:
                pass

        # TODO could be nice, but suppressing output should be a user choice
        def filter_tracebacks(bundle: list[str]) -> list[str]:
            ret = []
            tb = []

            for s in bundle:
                if s.startswith("Traceback (most recent call last):"):
                    if tb:
                        ret.append("\n".join(tb))
                        tb.clear()

                    tb.append(s)
                elif tb:
                    if not s.startswith(" "):
                        if "ExternalShutdownException" in s:
                            tb.clear()
                            ret.append("Node is shutting down: ExternalShutdownException")
                        elif "KeyboardInterrupt" in s:
                            tb.clear()
                            ret.append("Node is shutting down: KeyboardInterrupt")
                        else:
                            tb.append(s)
                    else:
                        tb.append(s)
                else:
                    ret.append(s)

            if tb:
                ret.append("\n".join(tb))

            return ret

        def log_bundle(bundle: list[str], level: int):
            # When receiving multiple lines of text at ones it is not guaranteed that they belong
            # together - we don't know if they were generated by a single log call or multiple.
            # By looking for our special pattern we can identify new log calls and emit them as
            # separate messages.
            seg = []
            for line in bundle:
                if seg and ros_message_pattern.search(line):
                    # Emit and start a new record
                    self.logger.log(level, "\n".join(seg))
                    seg = [line]
                else:
                    seg.append(line)
            if seg:
                self.logger.log(level, "\n".join(seg))

        # Output collection threads
        stdout_thread = threading.Thread(
            target=read_stream,
            args=(process.stdout, stdout_queue),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=read_stream,
            args=(process.stderr, stderr_queue),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()
        active_streams = 2

        try:
            # No need to check whether the process is still running, the collection threads
            # will terminate once no more data can be collected and reduce active_streams
            while active_streams > 0:
                out_bundle = collect_bundle(stdout_queue)
                if out_bundle:
                    log_bundle(out_bundle, logging.INFO)

                err_bundle = collect_bundle(stderr_queue)
                if err_bundle:
                    # err_bundle = filter_tracebacks(err_bundle)
                    log_bundle(err_bundle, logging.ERROR)

            returncode = process.poll()

            if returncode == 0:
                self.logger.warning("Process has finished cleanly")
            else:
                self.logger.critical(f"Process has died with exit code {returncode}")

        finally:
            self.logger.info(f"Terminated: {self}")

            if self._on_exit_callback:
                self._on_exit_callback()

            # Respawn the process if necessary
            from better_launch import BetterLaunch

            if not BetterLaunch.instance().is_shutdown and (
                self.max_respawns < 0 or self._respawn_retries < self.max_respawns
            ):
                self.logger.info(f"Restarting {repr(self)} after unexpected shutdown")

                self._respawn_retries += 1
                if self.respawn_delay > 0.0:
                    time.sleep(self.respawn_delay)

                # Not nice: this will run start from the watcher thread, which will then create
                # another watcher thread before this one here exits. Should be fine, just not
                # elegant.
                self.start()
            else:
                self._on_shutdown()

    def shutdown(
        self, reason: str, signum: int = signal.SIGTERM, timeout: float = 0.0
    ) -> None:
        if not self.is_running:
            return

        signame = signal.Signals(signum).name
        self.logger.warning(f"Received shutdown request: {reason} ({signame})")

        if signum == signal.SIGTERM and self._lifecycle_manager:
            try:
                self._lifecycle_manager.transition(LifecycleStage.FINALIZED)
            except Exception as e:
                self.logger.warning(f"Lifecycle transition to FINALIZED failed: {e}")

        self._on_signal(signum)

        if timeout == 0.0:
            return

        try:
            # Since introducing setpgrp above _process.wait hangs indefinitely
            # self._process.wait(timeout)
            os.waitpid(self.pid, 0)
        except subprocess.TimeoutExpired:
            raise TimeoutError("Node did not shutdown within the specified timeout")

    def _on_signal(self, signum) -> None:
        if not self._process or self._process.poll() is not None:
            return

        signame = signal.Signals(signum).name

        if not self.is_running:
            # the process is done or is cleaning up, no need to signal
            self.logger.info(
                f"{signame} not sent to {repr(self)} because it is already closing"
            )
            return

        if platform.system() == "Windows" and signum == signal.SIGINT:
            # Windows doesn't handle sigterm correctly
            self.logger.warning(
                "SIGINT not supported on Windows, escalating to 'SIGTERM'"
            )

            signum = signal.SIGTERM
            signame = signal.SIGTERM.name

        self.logger.info(f"Sending signal {signame} to {repr(self)}")

        try:
            # os.killpg(self.pid, signum)
            self._process.send_signal(signum)
        except ProcessLookupError:
            self.logger.info(
                f"{signame} not sent to {repr(self)} because it has closed already"
            )

    def _on_shutdown(self) -> None:
        if not self.is_running:
            return

        # Send SIGTERM and SIGKILL if not shutting down fast enough
        def escalate():
            try:
                time.sleep(3.0)
                self._on_signal(signal.SIGTERM)
                time.sleep(3.0)
                self._on_signal(signal.SIGKILL)
            except Exception:
                pass

        threading.Thread(target=escalate, daemon=True).start()

    def _get_info_section_general(self):
        info = super()._get_info_section_general()
        return (
            info
            + f"""
\x1b[1mProcess\x1b[0m
  PID:       {self.pid}
  Respawns:  {self._respawn_retries} / {self.max_respawns}
  Cmd Args:  {self.cmd_args}
  Env:       {self.env}
"""
        )

    def __repr__(self) -> str:
        return f"Node [name={self.name}, node={self.package}:{self.executable}, pid={self.pid}]"
