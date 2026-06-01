from typing import Any, Iterable
import os
import platform
import signal
import logging
import asyncio  # keep this so we can use await and async def
import threading
from multiprocessing import Process, Queue, get_context
import subprocess
import osrf_pycommon.process_utils
from setproctitle import setproctitle, getproctitle

from better_launch.utils.better_logging import (
    LogSink,
    ROSLOG_PATTERN_BL,
    ROSLOG_PATTERN_ROS,
    PrettyLogFormatter,
    RecordForwarder,
    StubbornHandler,
)
from better_launch.utils import settings
from better_launch.utils.colors import get_contrast_color
from .abstract_node import AbstractNode


def _launchservice_worker(
    name: str,
    launchservice_args: list[Any],
    launch_action_queue: Queue,
    log_queue: Queue,
    config: settings._Settings,
) -> None:
    """This function will run in a child process and will not have access to any objects already in memory UNLESS they are passed to it as arguments. See the comments for further details."""
    # Makes it easier to tell what's going on in the process table
    setproctitle(f"{getproctitle()} ({name})")

    if platform.system() != "Windows":
        # On unix-based systems this will make this process independent from the host process. This
        # way we can terminate it and its child processes without affecting the host process. Since
        # it's not supported on windows, we handle this in our shutdown function instead.
        os.setsid()

    # The child process will have clones of the host process' signal handlers installed (i.e. those
    # defined in launch_this), so we should rewire these, otherwise we'll get parallel calls
    def _on_sigint(signum: int, frame):
        try:
            ret = launch_service._shutdown(reason="SIGINT", due_to_sigint=True)
            if ret:
                # This way we suppress the "coroutine was never awaited" warning
                ret.close()
        finally:
            # Recommended to use this special _exit call in child processes
            os._exit(os.EX_OK)

    def _on_sigterm(signum: int, frame):
        # Recommended to use this special _exit call in child processes
        os._exit(os.EX_OK)

    signal.signal(signal.SIGINT, _on_sigint)
    signal.signal(signal.SIGTERM, _on_sigterm)

    # Late import to avoid adding ROS2 launch as a dependency - we are committed here!
    import launch

    # Synchronize the settings from the host process
    settings._SETTINGS = config

    # LaunchService is a little stubborn about log formatting and always prepends the node's
    # name and then appends the output format, but this also allows us to capture the actual
    # source of the message
    # NOTE this must be compatible with ROSLOG_PATTERN
    os.environ["RCUTILS_CONSOLE_OUTPUT_FORMAT"] = ROSLOG_PATTERN_ROS
    os.environ["RCUTILS_COLORIZED_OUTPUT"] = "0"

    # Create an offset to avoid going through the same sequence of colors as the host process
    get_contrast_color.hue = 0.3

    def handle_record(record: logging.LogRecord) -> None:
        try:
            log_queue.put_nowait(record)
        except Exception:
            # drop if parent not listening; prevents child spin
            pass

    std_handler = RecordForwarder(
        # TODO should always mimic the main process formatter configuration regarding colors etc.
        PrettyLogFormatter(
            config.screen_log_format,
            roslog_pattern=r"\[(?P<name>.+)] *" + ROSLOG_PATTERN_BL,
        )
    )
    std_handler.add_listener(handle_record)

    # The ROS2 launch system will set new formatters for each node and source, so our formatter
    # wouldn't be used. We either have to make our formatter more stubborn, or we run ROS2
    # in a proper subprocess and create a small launch file to load our actions. However,
    # there is no easy way to serialize a launch description...
    launch.logging.launch_config.screen_handler = StubbornHandler(std_handler)
    logger = launch.logging.get_logger(name)

    launch_service = launch.LaunchService(argv=launchservice_args, noninteractive=True)

    # This feels highly illegal and I love it! :>
    setattr(
        launch_service,
        f"_{launch_service.__class__.__name__}__logger",
        logger,
    )

    # Handle the queue through which we are receiving new launch actions
    loop = osrf_pycommon.process_utils.get_loop()

    def queue_watcher():
        while True:
            # multiprocessing.Queue cannot be awaited, so instead we are using a thread to block
            # indefinitely until we either receive something or the queue is closed.
            ld = launch_action_queue.get()

            if ld is None:
                # Most launch_service functions are thread safe and in fact DON'T seem
                # to work when called using loop.call_soon_threadsafe
                launch_service.shutdown()
                break

            launch_service.include_launch_description(ld)

    async def run():
        logger.info("Starting ROS2 launch service")

        # Start queue_watcher AFTER the event loop is running
        def start_queue_watcher():
            threading.Thread(target=queue_watcher, daemon=True).start()

        # Schedule queue_watcher to start after a brief delay
        loop.call_soon(start_queue_watcher)

        await launch_service.run_async(shutdown_when_idle=False)
        logger.info("ROS2 launch service has terminated")

    task = loop.create_task(run())

    try:
        loop.run_until_complete(task)
    except Exception as e:
        logger.warning(f"Error while running ROS2 launch service: {e}")
        raise


class Ros2LaunchWrapper(AbstractNode):
    def __init__(
        self,
        name: str = "LaunchService",
        launchservice_args: list[str] = None,
        output: LogSink | Iterable[LogSink] | Iterable[str] | str = LogSink.SCREEN,
    ):
        """Hosts a separate process running a ROS2 `LaunchService` instance (the main entrypoint of the ROS2 launch system).

        Note that although the ROS2 launch service may start an arbitrary number of nodes they will not be accessible for interaction beyond showing log output. Output on stdout and stderr from the process (and its nodes) will be captured, reformatted and separated by source.

        While this is a node-like object, it does not represent a node in ROS. This was done so that e.g. the TUI can be used to interact with the ROS2 launch system to e.g. include regular ROS2 launch files. Running a full process and a separate launch system is fairly resource heavy, however, `LaunchService` insists on running on the main thread.

        .. seealso::

            `ROS2 LaunchService <https://github.com/ros2/launch/blob/rolling/launch/launch/launch_service.py>`_

        Parameters
        ----------
        name : str, optional
            The name that will be used for the logger and the child process.
        launchservice_args : list[str], optional
            Additional arguments to pass to the ROS2 launch service. These will show up in the ROS2 `LaunchContext`.
        output : LogSink | Iterable[LogSink] | Iterable[str] | str, optional
            How log output from the launch service should be handled. This will also include the output from all nodes launched by this launch service. Common choices are `screen` to print to terminal, `log` to write to a common log file, `own_log` to write to a node-specific log file, and `none` to not write any output anywhere. See [configure_logger][utils.better_logging.configure_logger] for details.
        """
        super().__init__(
            "ros2/launch",
            "launch_service.py",
            name,
            "/",
            remaps=None,
            params=None,
            output=output,
        )

        self._launchservice_args = launchservice_args

        self._process: Process = None
        self._launch_action_queue = Queue()
        self._process_log_queue = Queue()
        self._loaded_launch_descriptions = []
        self._shutdown_requested = False
        self._terminate_requested = False

    @property
    def pid(self) -> int:
        """The process ID of the node process. Will be -1 if the process is not running."""
        if self._process:
            return self._process.pid
        return -1

    @property
    def launchservice_args(self) -> list[str]:
        """Additional arguments that are passed to the launch service."""
        return self._launchservice_args

    @property
    def is_running(self) -> bool:
        try:
            return self._process and self._process.is_alive()
        except ValueError:
            # For some reason we can't call is_alive when the process was closed
            return False

    def is_ros2_connected(self, timeout: float = None) -> bool:
        """Equal to [is_running][AbstractNode.is_running] for this class."""
        return self.is_running

    def is_lifecycle_node(self, timeout: float = None) -> bool:
        """This is never a lifecycle node."""
        return False

    def queue_ros2_actions(self, *actions) -> None:
        """Add ROS2 actions that will be loaded asynchronously by the launch service once it is running. Actions are bundled as a `LaunchDescription` before sending them off."""
        import launch

        ld = launch.LaunchDescription(list(actions))
        self._launch_action_queue.put(ld)
        self._loaded_launch_descriptions.append(ld)

    def join(self, timeout: float = None) -> None:
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
                proc.join(timeout)
            except subprocess.TimeoutExpired as e:
                raise TimeoutError from e

    def start(self) -> None:
        if self.is_running:
            self.logger.warning(f"LaunchService {self.name} is alrady running")
            return

        # Fix for https://github.com/dfki-ric/better_launch/issues/69
        # Python 3.14+ is switching to spawn as the default start method which means that our 
        # is-included guard in launch_this won't work anymore. Even if we used the env to pass
        # flags across spawn boundaries we still need to maintain the BetterLaunch singleton,
        # so for now fork is required.
        # TODO check if we can handle this in @launch_this instead
        ctx = get_context("fork")

        # Note that passing loggers will not work for the TUI, as they would have to communicate
        # across the process boundaries. In general, only basic values and instances from the
        # multiprocessing module should be passed to the process
        self._process = ctx.Process(
            target=_launchservice_worker,
            args=(
                self.name,
                self.launchservice_args,
                self._launch_action_queue,
                self._process_log_queue,
                settings.Settings(),
            ),
            name=self.name,
            daemon=True,
        )
        self._process.start()

        threading.Thread(target=self._process_watcher, daemon=True).start()

    def _process_watcher(self):
        q = self._process_log_queue

        while self.is_running:
            try:
                # Blocking call, if we don't receive anything the queue was closed
                record: logging.LogRecord = q.get()
                if record is None:
                    break

                self.logger.handle(record)
            except Exception as e:
                self.logger.error(f"Receiving log record failed: {e}")

        self._process.close()

    def shutdown(
        self, reason: str, signum: int = signal.SIGTERM, timeout: float = 0.0
    ) -> None:
        if self._terminate_requested and self.is_running:
            # Give the process a little bit of time to terminate
            try:
                self._process.join(0.5)
            except Exception:
                # Might fail during shutdown
                pass

        if not self.is_running:
            return

        try:
            if self._terminate_requested or signum == signal.SIGKILL:
                self.logger.warning(
                    f"{reason} - {self.name} was asked to terminate with SIGKILL. Killing the ROS2 launch service may leave stale processes behind!"
                )
                # Set the child process and all its children on fire
                self.send_signal(signal.SIGKILL)
            elif self._shutdown_requested:
                self._terminate_requested = True
                self.logger.info(
                    f"{self.name} is still runing, escalating to SIGTERM ({reason})"
                )
                # Rudely ask the child process and all its children to exit immediately
                self.send_signal(signal.SIGTERM)
            else:
                self._shutdown_requested = True
                self.logger.info(
                    f"Asking {self.name} to shutdown gracefully via SIGINT ({reason})"
                )
                # Gently suggest to the child process and all its children that they could exit now
                self.send_signal(signal.SIGINT)
        except Exception:
            pass

        if timeout == 0.0:
            return

        try:
            self._process.join(timeout)
        except subprocess.TimeoutExpired:
            raise TimeoutError(
                "ROS2 launch service did not shutdown within the specified timeout"
            )

    def send_signal(self, signum: int) -> None:
        if not self.is_running:
            return

        if platform.system() == "Windows":
            if signum == signal.SIGINT or signum == signal.SIGTERM:
                subprocess.call(["taskkill", "/PID", str(self.pid), "/T"])
            elif signum == signal.SIGKILL:
                subprocess.call(["taskkill", "/F", "/T", "/PID", str(self.pid)])
        else:
            os.killpg(os.getpgid(self.pid), signum)

    def _get_info_section_general(self) -> str:
        return (
            super()._get_info_section_general()
            + f"""\
\x1b[1mLaunch Service\x1b[0m
  PID:       {self.pid}
"""
        )

    def _get_info_section_ros(self) -> str:
        return f"""\
\x1b[1mLoaded Actions\x1b[0m
{self.describe_launch_actions()}
"""

    def describe_launch_actions(self) -> str:
        """Returns a best-effort summary of all `LaunchDescriptions` that have been loaded so far.

        Since ROS2 does not provide a way to serialize its slew of launch actions (beyond *maybe* pickle), it is not possible to create a full representation without special handlers. However, *most* launch actions expose their relevant data as properties. This function will look for these and recurse into them if they return launch actions.

        Returns
        -------
        str
            A formatted and indented representation of the launch descriptions scheduled for loading thus far.
        """
        descriptions = []

        for idx, ld in enumerate(self._loaded_launch_descriptions):
            info = f"({idx}) LaunchDescription(["
            for entity in ld.describe_sub_entities():
                info += "\n  " + self._format_properties(entity, 1) + ","
            info += "\n])"

            descriptions.append(info)

        return "\n".join(descriptions)

    def _format_properties(self, entity, depth: int = 0):
        indent = "    "
        description = f"{entity.__class__.__name__}("

        for param in dir(entity.__class__):
            if param == "self":
                continue

            if param.startswith("_"):
                continue

            val = getattr(type(entity), param)
            if not isinstance(val, property):
                continue

            val = val.fget(entity)

            # TODO some substitutions like LaunchDescriptionSource will only be resolved after
            # they have been executed by ROS2 launch, but we need to do this on the side of the
            # process, NOT in the host process where they are never run
            if val is None:
                val = "None"
            elif val.__class__.__module__.startswith("launch"):
                val = self._format_properties(val, depth + 1)
            elif isinstance(val, str):
                val = "'" + val + "'"

            description += f"\n{indent * (depth + 1)}{param} = {val},"

        description += f"\n{indent * depth})"
        return description
