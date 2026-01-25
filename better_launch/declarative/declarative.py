from typing import Any, Literal
import inspect
import contextlib
import logging

from better_launch import BetterLaunch
from better_launch.wrapper import _exec_launch_func
from better_launch.utils.better_logging import Colormode
from better_launch.utils.click import DeclaredArg

from .toml_parser import load as load_toml
from .substitutions import apply_substitutions


current_toml_format_version = 1


def _execute_toml(
    toml: dict[str, Any],
    eval_mode: Literal["full", "literal", "none"],
) -> dict[str, Any]:
    """Execute each call table and apply substitutions."""
    if BetterLaunch.instance():
        raise RuntimeError("BetterLaunch has already been initialized")

    # Initialize the launcher instance
    bl = BetterLaunch()
    valid_funcs = set(f for f in BetterLaunch.__dict__ if not f.startswith("_"))
    results = dict(bl.launch_args)

    def substitute_all(value: Any):
        if isinstance(value, dict):
            for key, val in value.items():
                value[key] = substitute_all(val)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                value[i] = substitute_all(item)
        elif isinstance(value, str):
            return apply_substitutions(value, None, results, eval_type=eval_mode)

        return value

    def exec_request(key: str, req: dict) -> Any:
        if "func" not in req:
            return

        substitute_all(req)

        if not req.pop("if", True):
            return

        if req.pop("unless", False):
            return

        # If not specified assume we're creating a node
        func_name = req.pop("func")
        if func_name not in valid_funcs:
            raise KeyError(f"func='{func_name}' is not a valid request")

        func = getattr(bl, func_name)
        func_sig = inspect.signature(func)

        # Where accepted the table key can be used as the name (e.g. of a node)
        if "name" in func_sig.parameters and "name" not in req:
            req["name"] = key

        # Call the function and store the result
        children = None
        if "children" not in func_sig.parameters:
            children = req.pop("children", None)

        res = func(**req)
        results[key] = res

        if children:
            if not isinstance(res, contextlib.AbstractContextManager):
                logging.getLogger().warning(
                    f"{req} has 'children' key, but did not result in a context object - children will be ignored"
                )
                return

            with res:
                # Must be a proper TOML subtable, we don't accept arrays of tables here
                if not isinstance(children, dict):
                    raise ValueError(f"Children of {key} must be specified as a dict")

                for subkey, child in children.items():
                    exec_request(subkey, child)

    # Sanitize the launch file
    toml.pop("__comment__", None)
    for key, val in toml.items():
        if isinstance(val, dict):
            for key in list(val.keys()):
                if key.startswith("__comment_"):
                    del val[key]

    # Execute the call tables
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
    extra_args: list[str] = None,
    eval_mode: Literal["full", "literal", "none"] = None,
    *,
    ui: bool = None,
    join: bool = None,
    screen_log_format: str = None,
    file_log_format: str = None,
    colormode: Colormode = None,
    manage_foreign_nodes: bool = None,
    keep_alive: bool = None,
    allow_kwargs: bool = None,
) -> None:
    """Execute a TOML better_launch launchfile.

    In better_launch TOML launch files, most tables will be `call tables`. A call table is a dict that has a `func` key referring to one of the public :py:class:`BetterLaunch` member functions. All other attributes will be treated as keyword arguments to that function. Call tables are executed in the order they appear in the launch file, and the result of calling their associated function will be stored under the call table's name.

    For example:

    .. code-block:: toml
        max_respawns = 3

        [my_awesome_node]
        func = "node"
        package = "my-package"
        executable = "my-node"
        name = "my-node"
        max_respawns = "${max_respawns}"

    This launch file declares a launch argument `max_respawns`. It then creates a new node and passes the launch argument to it using a substitution. The returned :py:class:`Node` instance is stored in the launch context under the `my_awesome_node` key, and could be referred to by later call tables.

    An example launchfile with more explanations can be found in the examples folder.

    Substitutions in better_launch take heavy inspiration from those found in ROS1 and should be familiar to many. However, as the TOML launchfile format is much more powerful, only the following substitutions were deemed necessary for now:
    - `${<K>}` this will resolve to a launch arg or call table result named <K>
    - `${param <N> <P>}` will retrieve a parameter <P> from the *full* nodename <N>
    - `${env <E> [D]}` will get the environment variable <E> (default to <D> if specified)
    - `${eval <X>}` will treat <X> as a python expression to evaluate (see `eval_mode` below)

    Substitutions can also be nested, in which case the innermost ones will be resolved first.

    For those functions in :py:class:`BetterLaunch` which are used as context objects (e.g. :py:meth:`BetterLaunch.group`, :py:meth:`BetterLaunch.compose`) you may provide a `children` attribute, which must be a dict of dicts. It's possible to use TOML's subtables for this like so:

    .. code-block:: toml
        [my_composer]
        func = "compose"

        [my_composer.children.talker]
        func = "component"
        package = "composition"
        plugin = "composition::Talker"

    In addition, any call table may contain an `if` and `unless` attribute to tie execution to a condition (which of course may contain substitutions). These will be evaluated according to
    python truthiness.
    - if     -> execute only if condition is true
    - unless -> execute only if condition is false

    Lastly, there are a couple of special keys that may be declared in the TOML:
    - `bl_toml_format`: the better_launch TOML parser version your launch file was written for. Set this if the format has changed and you don't want to update your launch file. The current version is :py:data:`toml_format_version`.
    - `bl_eval_mode`: if and how `$(eval ...)` substitutions should be supported.
    - `bl_ui`: default value for starting the UI
    - `bl_join`: whether to join the processes better_launch starts
    - `bl_colormode`: default colormode
    - `bl_screen_log_format`: default terminal output format
    - `bl_file_log_format`: default file log format
    - `bl_manage_foreign_nodes`: whether to show foreign nodes in the UI
    - `bl_keep_alive`: whether to keep running after the last node exits
    - `bl_allow_kwargs`: whether additional launch arguments are allowed

    Parameters
    ----------
    path : str
        Path to the TOML launchfile to execute.
    launch_args : dict[str, str], optional
        values for launch arguments declared by the launchfile.
    extra_args : list[str], optional
        Extra CLI arguments to pass through (e.g. node parameter overrides).
    eval_mode : Literal[&quot;full&quot;, &quot;literal&quot;, &quot;none&quot;], optional
        How to treat `eval` substitutions.
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
    allow_kwargs : bool, optional
        Whether additional launch arguments are allowed.
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

    # TODO establish and verify argument precedence:
    # CLI > env > launchfile > default

    if eval_mode is None:
        eval_mode = toml.get("bl_eval_mode", "literal")

    if ui is None:
        ui = toml.get("bl_ui", "false") in ("true", "enable", "1")

    if join is None:
        join = toml.get("bl_join", True)

    if colormode is None:
        colormode = Colormode[toml.get("bl_colormode", Colormode.DEFAULT.name)]

    if screen_log_format is None:
        screen_log_format = toml.get("bl_screen_log_format", None)

    if file_log_format is None:
        file_log_format = toml.get("bl_file_log_format", None)

    if manage_foreign_nodes is None:
        manage_foreign_nodes = toml.get("bl_manage_foreign_nodes", False)

    if keep_alive is None:
        keep_alive = toml.get("bl_keep_alive", False)

    if allow_kwargs is None:
        allow_kwargs = toml.get("bl_allow_kwargs", True)

    argv = None
    if launch_args:
        argv = []
        for key, arg in launch_args.items():
            if arg is not None:
                argv.extend([f"--{key}", arg])

    if extra_args:
        if argv is None:
            argv = []
        argv.extend(extra_args)

    def launch_func(*args, **kwargs):
        toml.update(kwargs)
        _execute_toml(toml, eval_mode=eval_mode)

    _exec_launch_func(
        launch_func,
        declared_args,
        docstring,
        ui=ui,
        join=join,
        colormode=colormode,
        screen_log_format=screen_log_format,
        file_log_format=file_log_format,
        manage_foreign_nodes=manage_foreign_nodes,
        keep_alive=keep_alive,
        # Not useful for the launchfile, but some node may consume the extra args
        allow_kwargs=allow_kwargs,
        _argv=argv,
    )
