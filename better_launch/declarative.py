from typing import Any
import inspect
import contextlib
import logging

from better_launch import BetterLaunch, convenience, gazebo
from better_launch.wrapper import _exec_launch_func
from better_launch.utils.settings import Colormode, _update_settings
from better_launch.utils.click import DeclaredArg
from better_launch.toml.toml_parser import load as load_toml
from better_launch.toml.substitutions import EvalMode, apply_substitutions


current_toml_format_version = 1


def _execute_toml(
    toml: dict[str, Any],
    eval_mode: EvalMode,
    **kwargs,
) -> dict[str, Any]:
    """Execute each call table and apply substitutions."""
    if BetterLaunch.instance():
        raise RuntimeError("BetterLaunch has already been initialized")

    # Apply any launch arguments, but prevent overriding call tables
    for key, val in kwargs.items():
        toml_val = toml.get(key)
        if isinstance(toml_val, dict) and "func" in toml_val:
            raise RuntimeError(f"Launcher tried to override TOML call table '{key}'")

        toml[key] = val

    # Initialize the launcher instance
    bl = BetterLaunch()

    #
    contexts = {
        "betterlaunch": {
            # instance functions
            name: func
            for name, func in inspect.getmembers(BetterLaunch, inspect.isfunction)
            if not name.startswith("_")
        }
        | {
            # class methods
            name: func
            for name, func in inspect.getmembers(BetterLaunch, inspect.ismethod)
            if not name.startswith("_")
        },
        "convenience": {
            name: func
            for name, func in inspect.getmembers(convenience, inspect.isfunction)
            if not name.startswith("_")
        },
        "gazebo": {
            name: func
            for name, func in inspect.getmembers(gazebo, inspect.isfunction)
            if not name.startswith("_")
        },
    }
    results = dict(bl.launch_args)

    def sanitize(data: dict) -> None:
        # Remove the comment keys that we kept in order to create help texts and such
        data.pop("__comment__", None)
        for key, val in toml.items():
            if isinstance(val, dict):
                for key in list(val.keys()):
                    if key.startswith("__comment_"):
                        del val[key]

    def substitute_all(value: Any):
        if isinstance(value, dict):
            for key, val in value.items():
                value[key] = substitute_all(val)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                value[i] = substitute_all(item)
        elif isinstance(value, str):
            new_val = apply_substitutions(value, None, results, eval_mode=eval_mode)
            return new_val

        return value

    def exec_request(key: str, req: dict) -> Any:
        if "func" not in req:
            return

        substitute_all(req)
        if not req.pop("if", True):
            results[key] = None
            return

        if req.pop("unless", False):
            results[key] = None
            return

        ctx = req.pop("context", "betterlaunch")
        if ctx not in contexts:
            raise KeyError(f"{key}: '{ctx}' is not a valid context")

        valid_funcs = contexts[ctx]

        # Get the function to execute
        func_name = req.pop("func")
        if func_name not in valid_funcs:
            raise KeyError(f"{key}: func='{func_name}' is not a valid function")

        func = valid_funcs[func_name]
        func_sig = inspect.signature(func)

        # Call the function and store the result
        children = None
        if "children" not in func_sig.parameters:
            children = req.pop("children", None)

        bl.logger.debug(f"Calling {ctx}:{func_name} ({req})")
        if ctx == "betterlaunch":
            if inspect.ismethod(func):
                # classmethod
                res = func(**req)
            else:
                # instance function
                res = func(bl, **req)
        else:
            res = func(**req)

        results[key] = res

        if children:
            if not isinstance(res, contextlib.AbstractContextManager):
                logging.getLogger().warning(
                    f"{req} has 'children' key, but did not result in a context object - children will be ignored"
                )
                return

            with res:
                if isinstance(children, list):
                    children = {
                        f"{key}.children.{idx}": child
                        for idx, child in enumerate(children)
                    }

                if not isinstance(children, dict):
                    raise ValueError(
                        f"Children of {key} must be specified as a dict or subtable"
                    )

                for subkey, child in children.items():
                    sanitize(child)
                    exec_request(subkey, child)

    # Execute the call tables
    sanitize(toml)
    for key, val in toml.items():
        if isinstance(val, dict):
            exec_request(key, val)
        else:
            results[key] = val

    return results


def _get_toml_args(toml: dict) -> list[DeclaredArg]:
    args = []

    for key, val in toml.items():
        if key.startswith("_"):
            continue

        if isinstance(val, dict) and "func" in val:
            continue

        if isinstance(val, type):
            # no default value
            ptype = val
            default = DeclaredArg._undefined
        else:
            ptype = type(val)
            default = val

        description = toml.get(f"__comment_{key}__")

        args.append(
            DeclaredArg(
                key,
                ptype,
                default,
                description,
            )
        )

    return args


def launch_toml(
    path: str,
    launch_args: dict[str, str] = None,
    *,
    # These should largely mirror the launch_this decorator
    ui: bool = None,
    colormode: Colormode = None,
    print_limit: int = None,
    screen_log_level: str | int = None,
    screen_log_format: str = None,
    file_log_level: str | int = None,
    file_log_format: str = None,
    use_sim_time: bool = None,
    eval_mode: str | EvalMode = None,
    join: bool = None,
    manage_foreign_nodes: bool = None,
    keep_alive: bool = None,
    allow_kwargs: bool = None,
) -> None:
    """Execute a TOML better_launch launchfile.

    In better_launch TOML launchfiles, most tables will be `call tables`. A call table is a dict that has a `func` key referring to one of the public [BetterLaunch][] member functions. All other attributes will be treated as keyword arguments to that function. Call tables are executed in the order they appear in the launch file, and the result of calling their associated function will be stored under the call table's name.

    For example:

    .. code-block:: toml
        name = "the-node-of-destiny"

        [my_awesome_node]
        func = "node"
        package = "my-package"
        executable = "my-node"
        name = "${name}"

    Substitutions are also possible and use a similar syntax as in ROS1 (as shown for the `name` launch argument above). `if` and `unless` conditions can be added as well.

    All parameters below can be set through the launch file by declaring them on the global scope with a `bl_` prefix (i.e. `ui` becomes `bl_ui`).

    Please see the documentation for full details.

    Parameters
    ----------
    path : str
        Path to the TOML launchfile to execute.
    launch_args : dict[str, str], optional
        values for launch arguments declared by the launchfile.
    eval_mode : Literal[&quot;full&quot;, &quot;literal&quot;, &quot;none&quot;], optional
        How to treat `eval` substitutions.
    ui : bool, optional
        Whether to start the better_launch TUI. Superseded by the `BL_UI` environment variable and the `--bl_ui_override` argument.
    allow_kwargs : bool, optional
        Whether additional launch arguments are allowed.
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
        Customize how log output will be formatted when printing it to the screen. Will be overridden by the `BL_SCREEN_LOG_FORMAT` environment variable. See [PrettyLogFormatter][utils.better_logging.PrettyLogFormatter] for details.
    file_log_level : str | int, optional
        The minimum level for log messages to be written to the lot file. Can be either  "info", "warning", "error", "critical", or an arbitrary integer (e.g. logging.WARNING).
    file_log_format : str, optional
        Customize how log output will be formatted when writing it to a file. Will be overridden by the `BL_FILE_LOG_FORMAT` environment variable. See [PrettyLogFormatter][utils.better_logging.PrettyLogFormatter] for details.
    manage_foreign_nodes : bool, optional
        If True, the TUI will also include node processes not started by this process. Has no effect if the TUI is not started.
    join : bool, optional
        If True, join the better_launch process. Has no effect when ui == True.
    keep_alive : bool, optional
        If True, keep the process alive even when all nodes have stopped.
    """
    toml: dict = load_toml(path)
    declared_args = _get_toml_args(toml)
    docstring = toml.get("__comment__")

    toml_format = int(toml.get("bl_toml_format", current_toml_format_version))
    if toml_format != current_toml_format_version:
        print(f"Warning: TOML launch file has unexpected format version {toml_format}")

    if toml_format == current_toml_format_version:
        pass
    # elif toml_format == some_previous_version: ...

    if not BetterLaunch.is_included():
        if ui is None and "bl_ui" in toml:
            ui = toml.get("bl_ui")
            if isinstance(ui, str):
                ui = bool(ui.lower() in ("true", "enable", "1"))

        if colormode is None and "bl_colormode" in toml:
            colormode = Colormode[toml["bl_colormode"]]

        if print_limit is None and "bl_print_limit" in toml:
            print_limit = int(toml["bl_print_limit"])

        if screen_log_level is None and "bl_screen_log_level" in toml:
            screen_log_level = int(toml["bl_screen_log_level"])

        if screen_log_format is None and "bl_screen_log_format" in toml:
            screen_log_format = toml["bl_screen_log_format"]

        if file_log_level is None and "bl_file_log_level" in toml:
            file_log_level = int(toml["bl_file_log_level"])

        if file_log_format is None and "bl_file_log_format" in toml:
            file_log_format = toml["bl_file_log_format"]

        if use_sim_time is None and "use_sim_time" in toml:
            use_sim_time = toml["use_sim_time"]

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

    if join is None:
        join = toml.get("bl_join", True)

    if manage_foreign_nodes is None:
        manage_foreign_nodes = toml.get("bl_manage_foreign_nodes", False)

    if keep_alive is None:
        keep_alive = toml.get("bl_keep_alive", False)

    if allow_kwargs is None:
        allow_kwargs = toml.get("bl_allow_kwargs", False)

    if eval_mode is None:
        eval_mode = EvalMode(toml.get("bl_eval_mode", "none"))
    elif isinstance(eval_mode, str):
        eval_mode = EvalMode(eval_mode)

    argv = []
    if launch_args:
        for key, arg in launch_args.items():
            if arg is not None:
                argv.extend([f"--{key}", str(arg)])

    def launch_func(*args, **kwargs):
        _execute_toml(toml, eval_mode=eval_mode, **kwargs)

    _exec_launch_func(
        launch_func,
        declared_args,
        docstring,
        launchfile=path,
        manage_foreign_nodes=manage_foreign_nodes,
        join=join,
        keep_alive=keep_alive,
        # Not useful for the launchfile, but some node may consume the extra args
        allow_kwargs=allow_kwargs,
        _argv=argv,
    )
