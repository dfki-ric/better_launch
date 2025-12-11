from typing import Any, Literal
import inspect
import contextlib
import logging

from better_launch import BetterLaunch
from better_launch.wrapper import _exec_launch_func
from better_launch.utils.settings import Colormode, _update_settings
from better_launch.utils.click import DeclaredArg

from .toml_parser import load as load_toml
from .substitutions import apply_substitutions


current_toml_format_version = 1


def _execute_toml(
    toml: dict[str, Any],
    eval_mode: Literal["full", "literal", "none"] = "literal",
) -> dict[str, Any]:
    """Execute each call table and apply substitutions."""
    if BetterLaunch.instance():
        raise RuntimeError("BetterLaunch has already been initialized")

    # Initialize the launcher instance
    bl = BetterLaunch()

    valid_funcs = {f: getattr(bl, f) for f in dir(bl) if not f.startswith("_")}
    results = dict(bl.launch_args)

    def substitute_all(value: Any):
        if isinstance(value, dict):
            for key, val in value.items():
                value[key] = substitute_all(val)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                value[i] = substitute_all(item)
        elif isinstance(value, str):
            new_val = apply_substitutions(value, None, results, eval_type=eval_mode)
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

        # Get the function to execute
        func_name = req.pop("func")
        if func_name not in valid_funcs:
            raise KeyError(f"func='{func_name}' is not a valid request")

        func = valid_funcs[func_name]
        func_sig = inspect.signature(func)

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
    *,
    # These should largely mirror the launch_this decorator
    ui: bool = None,
    colormode: Colormode = None,
    print_limit: int = 0,
    screen_log_level: str | int = None,
    screen_log_format: str = None,
    file_log_level: str | int = None,
    file_log_format: str = None,
    eval_mode: Literal["full", "literal", "none"] = "literal",
    join: bool = None,
    manage_foreign_nodes: bool = None,
    keep_alive: bool = None,
    allow_kwargs: bool = None,
) -> None:
    """Execute a TOML better_launch launchfile.

    In better_launch TOML launchfiles, most tables will be `call tables`. A call table is a dict that has a `func` key referring to one of the public :py:class:`BetterLaunch` member functions. All other attributes will be treated as keyword arguments to that function. Call tables are executed in the order they appear in the launch file, and the result of calling their associated function will be stored under the call table's name.

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

    Similar to :py:meth:`launch_this`, a TOML launchfile may specify various settings to configure the launch process. In particular, all of the *keyword-only* arguments to this function can be specified with a `bl_` prefix as global args. For example, to set the `screen_log_level` from your launchfile you could add `bl_screen_log_level = "warning"` in the global scope.

    Lastly, there are a couple of special keys that may be declared in the TOML:
    - `bl_toml_format`: the better_launch TOML parser version your launch file was written for. Set this if the format has changed and you don't want to update your launch file. The current version is :py:data:`toml_format_version`.
    
    Parameters
    ----------
    path : str
        Path to the TOML launchfile to execute.
    launch_args : dict[str, str], optional
        values for launch arguments declared by the launchfile.
    eval_mode : Literal[&quot;full&quot;, &quot;literal&quot;, &quot;none&quot;], optional
        How to treat `eval` substitutions.
    ui : bool, optional
        Whether to start the better_launch TUI. Superseded by the `BL_UI_OVERRIDE` environment variable and the `--bl_ui_override` argument.
    allow_kwargs : bool, optional
        Whether additional launch arguments are allowed.
    colormode : Colormode, optional
        Decides what colors will be used for:
        * default: one color per log severity level and a single color for all message sources
        * severity: one color per log severity, don't colorize message sources
        * source: one color per message source, don't colorize log severity
        * none: don't colorize anything
        * rainbow: colorize log severity and give each message source its own color
        Superseded by the `BL_COLORMODE_OVERRIDE` environment variable and the `--bl_colormode_override` argument.
    print_limit : int, optional
        Limit the length of messages printed to the screen.
    screen_log_level : str | int, optional
        The minimum level for log messages to be printed to the terminal/screen. Can be either  "info", "warning", "error", "critical", or an arbitrary integer (e.g. logging.WARNING).
    screen_log_format : str, optional
        Customize how log output will be formatted when printing it to the screen. Will be overridden by the `BL_SCREEN_LOG_FORMAT_OVERRIDE` environment variable. See :py:class:`PrettyLogFormatter` for details.
    file_log_level : str | int, optional
        The minimum level for log messages to be written to the lot file. Can be either  "info", "warning", "error", "critical", or an arbitrary integer (e.g. logging.WARNING).
    file_log_format : str, optional
        Customize how log output will be formatted when writing it to a file. Will be overridden by the `BL_FILE_LOG_FORMAT_OVERRIDE` environment variable. See :py:class:`PrettyLogFormatter` for details.
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
            ui = bool(toml.get("bl_ui", "false").lower() in ("true", "enable", "1"))

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

        _update_settings(
            ui=ui,
            colormode=colormode,
            print_limit=print_limit,
            screen_log_level=screen_log_level,
            screen_log_format=screen_log_format,
            file_log_level=file_log_level,
            file_log_format=file_log_format,
        )

    if join is None:
        join = toml.get("bl_join", True)

    if manage_foreign_nodes is None:
        manage_foreign_nodes = toml.get("bl_manage_foreign_nodes", False)

    if keep_alive is None:
        keep_alive = toml.get("bl_keep_alive", False)

    if allow_kwargs is None:
        allow_kwargs = toml.get("bl_allow_kwargs", False)

    argv = None
    if launch_args:
        argv = []
        for key, arg in launch_args.items():
            if arg is not None:
                argv.extend([f"--{key}", arg])

    def launch_func(*args, **kwargs):
        # TODO prevent using names of call tables
        toml.update(kwargs)
        _execute_toml(toml, eval_mode=eval_mode)

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
