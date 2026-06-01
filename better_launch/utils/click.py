from typing import Any, Type, Iterable, Callable
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
        key = param.name
        if param.name.startswith(("bl_", "bl-")):
            key = param.name[3:].replace("-", "_")
        _update_settings(**{key: value})

    # XXX always keep these synchronized with our Settings class
    options = [
        click.Option(
            ["--bl-ui"],
            type=bool,
            default=None,
            help="Enforce or prevent starting the TUI",
            expose_value=expose,  # not passed to our run method
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
        click.Option(
            ["--use-sim-time"],
            type=bool,
            default=None,  # NOTE important, see settings._update_settings
            help="Changes the default use_sim_time setting of the root group",
            expose_value=expose,
            callback=update_value,
        )
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
