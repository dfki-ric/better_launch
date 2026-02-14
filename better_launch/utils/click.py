from typing import Any, Type, Iterable, Callable
import json
from dataclasses import dataclass
import click

from better_launch.utils.settings import Colormode, _update_settings


@dataclass
class DeclaredArg:
    _undefined = object()

    name: str
    ptype: Type
    default: Any = _undefined
    description: str = None


def get_click_options(declared_args: Iterable[DeclaredArg]) -> list[click.Option]:
    options = []
    for arg in declared_args:
        if arg.default != DeclaredArg._undefined:
            default = arg.default
            required = False
        else:
            default = None
            required = True

        options.append(
            click.Option(
                [f"--{arg.name}"],
                type=arg.ptype,
                default=default,
                required=required,
                show_default=True,
                help=arg.description,
            )
        )

    return options


# TODO docstrings
def get_click_bl_options(expose: bool = False) -> list[click.Option]:
    """Get the click options specific to better_launch itself.

    Parameters
    ----------
    expose : bool, optional
        If True, click will forward these options to the command callback.

    Returns
    -------
    list[click.Option]
        _description_
    """

    def update_value(ctx: click.Context, param: click.Parameter, value: Any):
        key = param.name[3:].replace("-", "_")

        if value is not None:
            _update_settings(**{key: value})

        if key == "node_param_override" and value:
            ctx.command.allow_extra_args = True
            ctx.allow_extra_args = True

    def _bool_param_type(value: str) -> bool:
        """Convert string to boolean for Click options."""
        if isinstance(value, bool):
            return value
        val_lower = value.lower()
        if val_lower in ("true", "1", "yes", "on"):
            return True
        if val_lower in ("false", "0", "no", "off"):
            return False
        raise click.BadParameter(f"Invalid boolean value: {value}")

    # XXX always keep these synchronized with our Settings class
    options = [
        click.Option(
            ["--bl-ui"],
            type=_bool_param_type,
            default=None,
            help="Enforce or prevent starting the TUI",
            expose_value=expose,  # not passed to our run method
            callback=update_value,
        ),
        click.Option(
            ["--bl-node-param-override"],
            type=_bool_param_type,
            default=None,
            help="Allow overriding node parameters from the command line",
            expose_value=expose,
            callback=update_value,
        ),
        click.Option(
            ["--bl-colormode"],
            type=click.types.Choice([c.name for c in Colormode], case_sensitive=False),
            show_choices=True,
            default=None,
            help="Set the logging color mode",
            expose_value=expose,
            callback=update_value,
        ),
        click.Option(
            ["--bl-print-limit"],
            type=int,
            default=None,
            help="Cut off messages longer than this when printing to the terminal",
            expose_value=expose,
            callback=update_value,
        ),
        click.Option(
            ["--bl-screen-log-level"],
            type=click.types.Choice(
                ["debug", "info", "warning", "error", "critical", "fatal"],
                case_sensitive=False,
            ),
            show_choices=True,
            default=None,
            help="Only print log messages with at least this severity",
            expose_value=expose,
            callback=update_value,
        ),
        click.Option(
            ["--bl-screen-log-format"],
            type=str,
            default=None,
            help="Format used for printing log messages to the terminal",
            expose_value=expose,
            callback=update_value,
        ),
        click.Option(
            ["--bl-file-log-level"],
            type=click.types.Choice(
                ["debug", "info", "warning", "error", "critical", "fatal"],
                case_sensitive=False,
            ),
            show_choices=True,
            default=None,
            help="Only log messages with at least this severity",
            expose_value=expose,
            callback=update_value,
        ),
        click.Option(
            ["--bl-file-log-format"],
            type=str,
            default=None,
            help="Format used for writing log messages to the log file",
            expose_value=expose,
            callback=update_value,
        ),
    ]

    return options


def get_click_launch_command(
    cmd_name: str,
    launch_func: Callable,
    options: Iterable[click.Option],
    cmd_help: str = None,
    *,
    allow_kwargs: bool = False,
) -> click.Command:
    click_cmd = click.Command(
        cmd_name,
        callback=launch_func,
        params=options,
        help=cmd_help,
        context_settings={"ignore_unknown_options": True},
    )

    click_cmd.allow_extra_args = allow_kwargs
    click_cmd.ignore_unknown_options = True

    return click_cmd


def args_to_dict(args: list[str]) -> dict[str, Any]:
    """Convert a list of CLI arguments to a dictionary.

    Parameters
    ----------
    args : list[str]
        List of arguments, e.g. ["--foo", "bar", "--baz", "1.0"]

    Returns
    -------
    dict[str, Any]
        Dictionary of arguments, e.g. {"foo": "bar", "baz": 1.0}

    Raises
    ------
    ValueError
        If an argument does not start with "-" or if a value is missing.
    """
    result = {}
    it = iter(args)
    for arg in it:
        if not arg.startswith("-"):
            raise ValueError(f"Argument '{arg}' does not start with '-'")

        key = arg.lstrip("-")
        try:
            value = next(it)
        except StopIteration:
            raise ValueError(f"Missing value for argument '{arg}'")

        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass

        result[key] = value

    return result


def parse_node_params(
    kwargs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Separate node parameters from other keyword arguments.

    Node parameters are identified by containing a dot in their key. The part
    before the first dot is considered the node name, the part after the dot
    is the parameter name.

    Parameters
    ----------
    kwargs : dict[str, Any]
        Dictionary of keyword arguments.

    Returns
    -------
    tuple[dict[str, Any], dict[str, dict[str, Any]]]
        Remaining keyword arguments and a dictionary of node parameters.
    """
    remaining_kwargs = {}
    node_params = {}

    for key, value in kwargs.items():
        if "." in key:
            node_name, param_name = key.split(".", 1)
            if node_name not in node_params:
                node_params[node_name] = {}
            node_params[node_name][param_name] = value
        else:
            remaining_kwargs[key] = value

    return remaining_kwargs, node_params
