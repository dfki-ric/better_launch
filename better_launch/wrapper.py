from typing import Callable
import os
import builtins
import platform
from ast import literal_eval
import signal
import inspect
import click
import threading
import docstring_parser as doc

from better_launch.launcher import (
    BetterLaunch,
    _bl_singleton_instance,
    _bl_include_args,
)
from better_launch.utils.settings import Colormode, Settings, _update_settings
from better_launch.utils.better_logging import init_logging
from better_launch.utils.introspection import find_calling_frame
from better_launch.utils.click import (
    DeclaredArg,
    get_click_options,
    get_click_bl_options,
    get_click_launch_command,
)
from better_launch.ros import logging as roslog


_is_launcher_defined = "__better_launch_this_defined"


def launch_this(
    launch_func: Callable = None,
    *,
    ui: bool = False,
    colormode: Colormode = None,
    print_limit: int = None,
    screen_log_level: str | int = None,
    screen_log_format: str = None,
    file_log_level: str | int = None,
    file_log_format: str = None,
    use_sim_time: bool = None,
    manage_foreign_nodes: bool = False,
    join: bool = True,
    keep_alive: bool = False,
):
    """Use this to decorate your launch function. The function will be run automatically. The function is allowed to block even when using the UI.

    **NOTE:** this decorator cannot be used more than once per module.

    Parameters
    ----------
    launch_func : Callable, optional
        Your launch function, typically using BetterLaunch to start ROS2 nodes.
    ui : bool, optional
        Whether to start the better_launch TUI. Superseded by the `BL_UI` environment variable and the `--bl_ui_override` argument.
    colormode : Colormode, optional
        Decides what colors will be used for:
        * default: one color per log severity level and a single color for all message sources
        * severity: one color per log severity, don't colorize message sources
        * source: one color per message source, don't colorize log severity
        * none: don't colorize anything
        * rainbow: colorize log severity and give each message source its own color
        Superseded by the `BL_COLORMODE` environment variable and the `--bl_colormode_override` argument.
    print_limit : int, optional
        Limit the length of messages printed to the screen.
    screen_log_level : str | int, optional
        The minimum level for log messages to be printed to the terminal/screen. Can be either  "info", "warning", "error", "critical", or an arbitrary integer (e.g. logging.WARNING).
    screen_log_format : str, optional
        Customize how log output will be formatted when printing it to the screen. Will be overridden by the `BL_SCREEN_LOG_FORMAT` environment variable. See [PrettyLogFormatter][better_launch.utils.better_logging.PrettyLogFormatter] for details.
    file_log_level : str | int, optional
        The minimum level for log messages to be written to the lot file. Can be either  "info", "warning", "error", "critical", or an arbitrary integer (e.g. logging.WARNING).
    file_log_format : str, optional
        Customize how log output will be formatted when writing it to a file. Will be overridden by the `BL_FILE_LOG_FORMAT` environment variable. See [PrettyLogFormatter][better_launch.utils.better_logging.PrettyLogFormatter] for details.
    manage_foreign_nodes : bool, optional
        If True, the TUI will also include node processes not started by this process. Has no effect if the TUI is not started.
    join : bool, optional
        If True, join the better_launch process. Has no effect when ui == True.
    keep_alive : bool, optional
        If True, keep the process alive even when all nodes have stopped.
    """

    # Settings of included launchfiles will be ignored
    # NOTE be careful not to instantiate BetterLaunch before the launch function has run
    if not BetterLaunch.is_included():
        _update_settings(
            ui=ui,
            colormode=colormode,
            print_limit=print_limit,
            screen_log_level=screen_log_level,
            screen_log_format=screen_log_format,
            file_log_level=file_log_level,
            file_log_format=file_log_format,
            use_sim_time=use_sim_time,
        )

    def decoration_helper(func):
        sig = inspect.signature(func)
        declared_args = _get_declared_args(sig, func.__doc__)

        func_doc = doc.parse(func.__doc__)

        argspec = inspect.getfullargspec(func)
        allow_kwargs = argspec[2] is not None

        return _exec_launch_func(
            func,
            declared_args,
            func_doc,
            join=join,
            manage_foreign_nodes=manage_foreign_nodes,
            keep_alive=keep_alive,
            allow_kwargs=allow_kwargs,
        )

    return decoration_helper if launch_func is None else decoration_helper(launch_func)


def _init_signal_handlers() -> None:
    # Signal handlers have to be installed on the main thread. Since the BetterLaunch singleton
    # could be instantiated first on a different thread we do it here where we can make stronger
    # requirements.
    if threading.current_thread() != threading.main_thread():
        raise RuntimeError("launch_this must be used on the main thread")

    sigint_count = 0

    def sigint_handler(sig, frame):
        nonlocal sigint_count
        sigint_count += 1

        # Some terminals will send SIGINT multiple times on ctrl-c, so we ignore the second one
        if sigint_count == 2:
            return

        BetterLaunch()._on_sigint(sig, frame)

    def sigterm_handler(sig, frame):
        BetterLaunch()._on_sigterm(sig, frame)

    signal.signal(signal.SIGINT, sigint_handler)
    signal.signal(signal.SIGTERM, sigterm_handler)

    if platform.system() != "Windows":
        signal.signal(signal.SIGQUIT, sigterm_handler)


def _get_declared_args(
    signature: inspect.Signature, docstring: str = None
) -> list[DeclaredArg]:
    # Extract more fine-grained information from the docstring
    param_docstrings = {}
    if docstring:
        parsed_doc = doc.parse(docstring)
        param_docstrings = {p.arg_name: p.description for p in parsed_doc.params}

    declared_args = []

    # Create CLI options for click
    for param in signature.parameters.values():
        ptype = None
        default = DeclaredArg._undefined

        if param.annotation is not param.empty:
            ptype = param.annotation
            if ptype and isinstance(ptype, str):
                # If it's a primitive type we can parse it, otherwise ignore it
                # NOTE use the proper builtins module here, __builtins__ is unreliable
                ptype = getattr(builtins, ptype, None)

        if param.default is not inspect.Parameter.empty:
            default = param.default

            if ptype is None and default is not None:
                ptype = type(default)

        declared_args.append(
            DeclaredArg(param.name, ptype, default, param_docstrings.get(param.name))
        )

    return declared_args


def _exec_launch_func(
    launch_func: Callable,
    declared_args: list[DeclaredArg],
    func_doc: str = None,
    *,
    launchfile: str = None,
    manage_foreign_nodes: bool = False,
    join: bool = True,
    keep_alive: bool = False,
    allow_kwargs: bool = False,
    # NOTE for internal use only, we don't want launchfiles that ignore their CLI args
    _argv: list[str] = None,
):
    # NOTE this function should not make any assumptions about the launch_func

    # Globals of the calling module
    launch_frame = find_calling_frame(_exec_launch_func)
    glob = launch_frame.frame.f_globals

    if glob.get(_is_launcher_defined, False) and _bl_singleton_instance not in glob:
        # Allow using launch_this only once unless we got included from another file
        raise RuntimeError("Can only use one launch decorator")

    glob[_is_launcher_defined] = True

    # NOTE be careful not to instantiate BetterLaunch before the launch function has run
    if BetterLaunch.is_included():
        # We have been included from another file, run the launch function and skip the remaining
        # initialization as its already been taken care of
        bl: BetterLaunch = glob[_bl_singleton_instance]

        includefile = launch_frame.filename
        include_args: dict = glob[_bl_include_args]
        bl.logger.info(f"Including launch file: {includefile} (args={include_args})")

        call_kw = {
            a.name: a.default
            for a in declared_args
            if a.default != DeclaredArg._undefined
        }

        for key, val in include_args.items():
            if allow_kwargs or key in call_kw:
                call_kw[key] = val

        launch_func(**call_kw)

        return

    # Get the filename of the original launchfile
    # At this point we know that we are the main launch file
    if launchfile:
        BetterLaunch._launchfile = launchfile
    else:
        BetterLaunch._launchfile = launch_frame.filename

    _init_signal_handlers()

    # If we were started by ros launch (e.g. through 'ros2 launch <some-bl-launch-file>') we need
    # to expose a "generate_launch_description" method instead of running by ourselves.
    #
    # Launch files in ROS2 are run by adding an IncludeLaunchDescription action to the
    # LaunchService (both found in https://github.com/ros2/launch/). When the action is resolved,
    # it ultimately leads to get_launch_description_from_python_launch_file, which imports the file
    # and then checks for a generate_launch_description function.
    #
    # See the following links for details:
    #
    # https://github.com/ros2/launch_ros/blob/rolling/ros2launch/ros2launch/command/launch.py#L125
    # https://github.com/ros2/launch_ros/blob/rolling/ros2launch/ros2launch/api/api.py#L141
    # https://github.com/ros2/launch/blob/rolling/launch/launch/actions/include_launch_description.py#L148
    # https://github.com/ros2/launch/blob/rolling/launch/launch/launch_description_sources/python_launch_file_utilities.py#L43
    stack = inspect.stack()
    for frame_info in stack:
        frame_locals = frame_info.frame.f_locals
        if "self" not in frame_locals:
            continue

        owner = frame_locals["self"]

        if type(owner).__name__ == "IncludeLaunchDescription":
            # We were included or started by ROS2, expose the expected launch method in our
            # caller's globals and return
            print(
                f"[NOTE] Launch file {os.path.basename(BetterLaunch._launchfile)} got included from ROS2"
            )

            # TODO Maybe we shouldn't?
            init_logging(roslog.launch_config)

            _expose_ros2_launch_function(launch_func, declared_args)
            return

    # If we get here we were not included by ROS2

    @click.pass_context
    def run(ctx: click.Context, *args, **kwargs):
        init_logging(roslog.launch_config)

        if allow_kwargs:
            # If the launch func defines a **kwarg we can pass all extra arguments to it, with
            # the caveat that these extra args need to be defined as `-[-]<key> val` tuples.
            assert len(ctx.args) % 2 == 0, (
                f"extra arguments need to be '--<key> <value>' tuples ({ctx.args})"
            )

            for i in range(0, len(ctx.args), 2):
                key = ctx.args[i]
                if not key.startswith("-"):
                    raise ValueError("Extra argument keys must start with a dash")

                val = ctx.args[i + 1]
                try:
                    val = literal_eval(val)
                except Exception:
                    # Keep val as a string
                    pass

                kwargs[key.strip("-")] = val

        # By default BetterLaunch has access to all arguments from its launch function
        BetterLaunch._launch_func_args = dict(kwargs)

        # Wrap the launch function so we can do some preparation and cleanup tasks.
        def launch_func_wrapper():
            try:
                # Execute the launch function!
                launch_func(*args, **kwargs)
            except Exception as e:
                bl = BetterLaunch.instance()
                if bl and not bl.is_shutdown:
                    bl.shutdown(f"Exception in launch file: {e}")

                raise

            # Retrieve the BetterLaunch singleton
            bl = BetterLaunch()

            # The UI will manage spinning itself
            if join and not Settings().ui:
                bl.spin(exit_with_last_node=not keep_alive)

        if Settings().ui:
            from better_launch.tui.better_tui import BetterTui

            app = BetterTui(
                launch_func_wrapper,
                manage_foreign_nodes=manage_foreign_nodes,
                keep_alive=keep_alive,
            )
            app.run()
        else:
            launch_func_wrapper()

    options = get_click_options(declared_args)
    options.extend(get_click_bl_options())

    click_cmd = get_click_launch_command(
        BetterLaunch._launchfile,
        run,
        options,
        func_doc,
        allow_kwargs=allow_kwargs,
    )

    if allow_kwargs:
        click_cmd.allow_extra_args = True
        click_cmd.ignore_unknown_options = True

    try:
        click_cmd.main(_argv)
    except SystemExit as e:
        if e.code != 0:
            raise


def _expose_ros2_launch_function(
    launch_func: Callable, declared_args: list[DeclaredArg]
):
    """Helper function that exposes a function decorated by launch_this so that it can be included by a regular ROS2 launch file. We achieve this by generating a `generate_launch_description` function and adding it to the module globals where the launch function is defined.

    Parameters
    ----------
    launch_func : Callable
        The launch function.
    declared_args : list[LaunchArg]
        Arguments that should be declared.
    """

    def generate_launch_description():
        import asyncio
        from launch import LaunchDescription, LaunchContext
        from launch.actions import DeclareLaunchArgument, OpaqueCoroutine

        ld = LaunchDescription()

        # Declare launch arguments from the function signature
        for arg in declared_args:
            default = None
            if arg.default not in (None, DeclaredArg._undefined):
                default = str(arg.default)

            ld.add_action(DeclareLaunchArgument(arg.name, default_value=default))

        async def ros2_wrapper(context: LaunchContext):
            launch_args = {}
            for k, v in context.launch_configurations.items():
                try:
                    launch_args[k] = literal_eval(v)
                except (ValueError, SyntaxError):
                    # Probably a string
                    # issue #11: SyntaxError happens when a path is passed without quotes
                    # NOTE this should also make passing args to ROS2 much easier
                    launch_args[k] = v

            # Call the launch function
            launch_func(**launch_args)

            # We must stay alive until the last node has exited
            bl = BetterLaunch.instance()
            if bl:
                while any([n for n in bl.get_nodes() if n.is_running]):
                    await asyncio.sleep(0.1)

        # A bit of an obscure one, but this way we can stay alive even when all other launch
        # actions have terminated
        ld.add_action(OpaqueCoroutine(coroutine=ros2_wrapper))
        return ld

    # Add our generate_launch_description function to the module launch_this was called from
    launch_frame = find_calling_frame(_exec_launch_func)
    caller_globals = launch_frame.frame.f_globals
    caller_globals["generate_launch_description"] = generate_launch_description
