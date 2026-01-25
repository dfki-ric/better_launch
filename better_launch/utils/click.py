from typing import Any, Type, Iterable, Callable
import json
import os

from dataclasses import dataclass
import click

from better_launch.utils.better_logging import Colormode


@dataclass
class DeclaredArg:
    _undefined = object()

    name: str
    ptype: Type
    default: Any = _undefined
    description: str = None


@dataclass
class Overrides:
    ui: bool = False
    node_param_override: bool = False
    colormode = Colormode.DEFAULT
    screen_log_format: str = None
    file_log_format: str = None

    def __init__(
        self,
        ui: bool = False,
        node_param_override: bool = False,
        colormode: Colormode = Colormode.DEFAULT,
        screen_log_format: str = None,
        file_log_format: str = None,
    ):
        env_ui = os.environ.get("BL_UI_OVERRIDE", str(ui)).lower()
        self.ui = env_ui in ("enable", "true", "1")

        env_node_param_override = os.environ.get(
            "BL_NODE_PARAM_OVERRIDE", str(node_param_override)
        ).lower()
        self.node_param_override = env_node_param_override in ("enable", "true", "1")

        env_colormode = os.environ.get("BL_COLORMODE_OVERRIDE", colormode.name)
        self.colormode = Colormode[env_colormode.upper()]

        self.screen_log_format = os.environ.get(
            "BL_SCREEN_LOG_FORMAT_OVERRIDE", screen_log_format
        )
        self.file_log_format = os.environ.get(
            "BL_FILE_LOG_FORMAT_OVERRIDE", file_log_format
        )


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


def get_click_overrides(
    overrides: Overrides, expose: bool = False
) -> list[click.Option]:
    # Additional overrides for launch arguments
    def set_override_ui(ctx: click.Context, param: click.Parameter, value: str):
        if value != "unset":
            overrides.ui = value == "enable"
        return value

    def set_override_node_params(
        ctx: click.Context, param: click.Parameter, value: str
    ):
        if value != "unset":
            overrides.node_param_override = value == "enable"
            if overrides.node_param_override:
                ctx.allow_extra_args = True
        return value

    def set_override_colormode(ctx: click.Context, param: click.Parameter, value: str):
        if value:
            overrides.colormode = Colormode[value.upper()]
        return value

    # NOTE these should be mirrored in the bl script
    options = [
        click.Option(
            ["--bl_ui_override"],
            type=click.types.Choice(
                ["enable", "disable", "unset"], case_sensitive=False
            ),
            show_choices=True,
            default="unset",
            help="Override to enable/disable the terminal UI",
            expose_value=expose,  # not passed to our run method
            callback=set_override_ui,
        ),
        click.Option(
            ["--bl_node_param_override"],
            type=click.types.Choice(
                ["enable", "disable", "unset"], case_sensitive=False
            ),
            show_choices=True,
            default="unset",
            help="Override to enable/disable node parameter overrides",
            expose_value=expose,
            callback=set_override_node_params,
        ),
        click.Option(
            ["--bl_colormode_override"],
            type=click.types.Choice([c.name for c in Colormode], case_sensitive=False),
            show_choices=True,
            default=None,
            help="Override the logging color mode",
            expose_value=expose,
            callback=set_override_colormode,
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
    """
    Convert a list of CLI arguments to a dictionary.

    Args:
        args: List like ['--my_node.rate', '10', '--verbose', 'true']

    Returns:
        Dict like {'my_node.rate': 10, 'verbose': True}

    Values are parsed as JSON if possible, otherwise kept as strings.
    """
    result = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg.startswith("-"):
            raise ValueError("Extra argument keys must start with a dash")

        if i + 1 >= len(args):
            raise ValueError(
                f"extra arguments need to be '--<key> <value>' tuples ({args})"
            )

        key = arg.lstrip("-")
        value_str = args[i + 1]
        try:
            value = json.loads(value_str)
        except (ValueError, json.JSONDecodeError):
            value = value_str
        result[key] = value
        i += 2

    return result


def parse_node_params(
    kwargs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """
    Extract node.param keys from kwargs dict.

    Args:
        kwargs: Dict of CLI arguments (e.g., {'my_node.rate': 10, 'verbose': True})

    Returns:
        Tuple of (remaining_kwargs, node_params) where:
        - remaining_kwargs: Kwargs that weren't node params
        - node_params: Dict like {'my_node': {'rate': 10}}
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
