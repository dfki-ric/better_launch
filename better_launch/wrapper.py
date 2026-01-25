from typing import Callable
from ast import literal_eval
import os
import sys
import platform

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
from better_launch.utils.better_logging import (
    Colormode,
    init_logging,
)
from better_launch.utils.introspection import find_calling_frame
from better_launch.utils.click import (
    DeclaredArg,
    Overrides,
    get_click_options,
    get_click_overrides,
    get_click_launch_command,
    parse_node_params,
    args_to_dict,
)
from better_launch.ros import logging as roslog


_is_launcher_defined = "__better_launch_this_defined"


def launch_this(
    launch_func: Callable = None,
    *,
    ui: bool = False,
    join: bool = True,
    screen_log_format: str = None,
    file_log_format: str = None,
    colormode: Colormode = Colormode.DEFAULT,
    manage_foreign_nodes: bool = False,
    keep_alive: bool = False,
):
    """Use this to decorate your launch function. The function will be run automatically. The function is allowed to block even when using the UI.

    **NOTE:** this decorator cannot be used more than once per module.

    Parameters
    ----------
    launch_func : Callable, optional
        Your launch function, typically using BetterLaunch to start ROS2 nodes.
    ui : bool, optional
        Whether to start the better_launch TUI. Superseded by the `BL_UI_OVERRIDE` environment variable and the `--bl_ui_override` argument.
    join : bool, optional
        If True, join the better_launch process. Has no effect when ui == True.
    screen_log_format : str, optional
        Customize how log output will be formatted when printing it to the screen. Will be overridden by the `BL_SCREEN_LOG_FORMAT_OVERRIDE` environment variable. See :py:class:`PrettyLogFormatter` for details.
    file_log_format : str, optional
        Customize how log output will be formatted when writing it to a file. Will be overridden by the `BL_FILE_LOG_FORMAT_OVERRIDE` environment variable. See :py:class:`PrettyLogFormatter` for details.
    colormode : Colormode, optional
        Decides what colors will be used for:
        * default: one color per log severity level and a single color for all message sources
        * severity: one color per log severity, don't colorize message sources
        * source: one color per message source, don't colorize log severity
        * none: don't colorize anything
        * rainbow: colorize log severity and give each message source its own color
        Superseded by the `BL_COLORMODE_OVERRIDE` environment variable and the `--bl_colormode_override` argument.
    manage_foreign_nodes : bool, optional
        If True, the TUI will also include node processes not started by this process. Has no effect if the TUI is not started.
    keep_alive : bool, optional
        If True, keep the process alive even when all nodes have stopped.
    """

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
            ui=ui,
            join=join,
            screen_log_format=screen_log_format,
            file_log_format=file_log_format,
            colormode=colormode,
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

        if param.default is not param.empty:
            default = param.default

            if default is not None:
                ptype = type(default)
            elif param.annotation is not param.empty:
                ptype = param.annotation
                if isinstance(ptype, str):
                    # If it's a primitive type we can parse it, otherwise ignore it
                    ptype = getattr(__builtins__, ptype, None)

        # type, default, docstring
        declared_args.append(
            DeclaredArg(param.name, ptype, default, param_docstrings.get(param.name))
        )

    return declared_args


def _exec_launch_func(
    launch_func: Callable,
    declared_args: list[DeclaredArg],
    func_doc: str = None,
    *,
    ui: bool = False,
    join: bool = True,
    screen_log_format: str = None,
    file_log_format: str = None,
    colormode: Colormode = Colormode.DEFAULT,
    manage_foreign_nodes: bool = False,
    keep_alive: bool = False,
    allow_kwargs: bool = False,
    # NOTE for internal use only, we don't want launchfiles that ignore their CLI args
    _argv: list[str] = None,
):
    # NOTE this function should not make any assumptions about the launch_func

    # Globals of the calling module
    glob = find_calling_frame(_exec_launch_func).frame.f_globals

    if glob.get(_is_launcher_defined, False) and _bl_singleton_instance not in glob:
        # Allow using launch_this only once unless we got included from another file
        raise RuntimeError("Can only use one launch decorator")

    glob[_is_launcher_defined] = True

    # Get the filename of the original launchfile
    # NOTE be careful not to instantiate BetterLaunch before launch_func has run
    if _bl_singleton_instance not in glob:
        BetterLaunch._launchfile = find_calling_frame(_exec_launch_func).filename
        print(f"Starting launch file:\n{BetterLaunch._launchfile}\n")
        print(f"Log files will be saved at\n{roslog.launch_config.log_dir}\n")
        print("==================================================")
    else:
        # We have been included from another file, run the launch function and skip the remaining
        # initialization as its already been taken care of
        bl: BetterLaunch = glob[_bl_singleton_instance]

        includefile = find_calling_frame(_exec_launch_func).filename
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

    # At this point we know that we are the main launch file

    _init_signal_handlers()

    overrides = Overrides(
        ui=ui,
        colormode=colormode,
        screen_log_format=screen_log_format,
        file_log_format=file_log_format,
    )

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
            init_logging(
                roslog.launch_config,
                overrides.screen_log_format,
                overrides.file_log_format,
                overrides.colormode,
            )

            _expose_ros2_launch_function(launch_func, declared_args)
            return

    # If we get here we were not included by ROS2

    @click.pass_context
    def run(ctx: click.Context, *args, **kwargs):
        init_logging(
            roslog.launch_config,
            overrides.screen_log_format,
            overrides.file_log_format,
            overrides.colormode,
        )

        # Parse node-specific param overrides from ctx.args (extra unknown args)
        # Convert ctx.args list to dict, then extract node params
        extra_args_dict = args_to_dict(ctx.args)
        remaining_kwargs, node_overrides = parse_node_params(extra_args_dict)
        applied_overrides = node_overrides if overrides.node_param_override else {}
        if applied_overrides:
            BetterLaunch().set_node_param_overrides(applied_overrides)

        if allow_kwargs and remaining_kwargs:
            for key, value in remaining_kwargs.items():
                if isinstance(value, str):
                    try:
                        value = literal_eval(value)
                    except Exception:
                        pass
                kwargs[key] = value

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
            if join and not overrides.ui:
                bl.spin(exit_with_last_node=not keep_alive)

        if overrides.ui:
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
    options.extend(get_click_overrides(overrides))

    click_cmd = get_click_launch_command(
        BetterLaunch._launchfile,
        run,
        options,
        func_doc,
        allow_kwargs=allow_kwargs,
    )

    if allow_kwargs or overrides.node_param_override:
        click_cmd.allow_extra_args = True

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
