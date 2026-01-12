from typing import Any, Type, Iterable, Callable
import os
from dataclasses import dataclass, field
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
    colormode = Colormode.DEFAULT
    screen_log_format: str = None
    file_log_format: str = None
    node_params: list[tuple[str, str, str]] = field(default_factory=list)

    def __init__(
        self,
        ui: bool = False,
        colormode: Colormode = Colormode.DEFAULT,
        screen_log_format: str = None,
        file_log_format: str = None,
        node_params: list[tuple[str, str, str]] = None,
    ):
        env_ui = os.environ.get("BL_UI_OVERRIDE", str(ui)).lower()
        self.ui = env_ui in ("enable", "true", "1")

        env_colormode = os.environ.get("BL_COLORMODE_OVERRIDE", colormode.name)
        self.colormode = Colormode[env_colormode.upper()]

        self.screen_log_format = os.environ.get(
            "BL_SCREEN_LOG_FORMAT_OVERRIDE", screen_log_format
        )
        self.file_log_format = os.environ.get(
            "BL_FILE_LOG_FORMAT_OVERRIDE", file_log_format
        )
        self.node_params = node_params or []


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

    def set_override_colormode(ctx: click.Context, param: click.Parameter, value: str):
        if value:
            overrides.colormode = Colormode[value.upper()]
        return value

    def set_override_node_param(
        ctx: click.Context, param: click.Parameter, value: list[tuple[str, str, str]]
    ):
        if value:
            overrides.node_params = value
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
            ["--bl_colormode_override"],
            type=click.types.Choice([c.name for c in Colormode], case_sensitive=False),
            show_choices=True,
            default=None,
            help="Override the logging color mode",
            expose_value=expose,
            callback=set_override_colormode,
        ),
        click.Option(
            ["--node_param"],
            type=(str, str, str),
            multiple=True,
            help="Override a node parameter: <node_name> <param_name> <value>",
            expose_value=expose,
            callback=set_override_node_param,
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
        cmd_name, callback=launch_func, params=options, help=cmd_help
    )

    if allow_kwargs:
        click_cmd.allow_extra_args = True
        click_cmd.ignore_unknown_options = True

    return click_cmd
