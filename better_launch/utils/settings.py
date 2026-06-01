from typing import Any
import os
import logging
from enum import IntEnum
from dataclasses import dataclass, fields, replace, asdict


class Colormode(IntEnum):
    # Color messages based on their severity and highlight the sources in one color
    DEFAULT = 0

    # Color messages only based on their severity
    SEVERITY = 1

    # Color messages only based on the logging source
    SOURCE = 2

    # Don"t color messages
    NONE = 3

    # Give a different color to each severity and logging source
    RAINBOW = 4


def severity_to_loglevel(severity: str) -> int:
    if not severity:
        return logging.INFO

    loglevels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
        "FATAL": logging.FATAL,
    }
    return loglevels.get(severity.upper(), logging.INFO)


default_screen_format = "[{levelcolor_start}{levelname}{levelcolor_end}] [{sourcecolor_start}{name}{sourcecolor_end}] [{asctime}]\n{message}"

default_file_format = "[{levelname}] [{asctime}] {message}"


@dataclass(frozen=True)
class _Settings:
    ui: bool = False
    colormode: Colormode = Colormode.DEFAULT
    print_limit: int = 0
    screen_log_level: int = logging.INFO
    file_log_level: int = logging.INFO
    screen_log_format: str = default_screen_format
    file_log_format: str = default_file_format
    use_sim_time: bool = False

    def __init__(self, **kwargs):
        """
        Initialize settings with priority: env vars > kwargs > defaults.

        Parameters
        ----------
        kwargs
            Function-level overrides
        """
        for field in fields(self):
            # Get environment variable value
            key = f"BL_{field.name.upper()}"
            val = self._get_env_value(key, field.type)

            # Resolve priority: env > kwargs > default
            if val is not None:
                res = val
            elif field.name in kwargs:
                res = kwargs[field.name]
            else:
                # Get default value from field
                res = (
                    field.default
                    if field.default is not field.default_factory
                    else field.default_factory()
                )

            # Cannot use regular setattr in a frozen dataclass
            object.__setattr__(self, field.name, res)

    def _get_env_value(self, env_key: str, field_type: type) -> Any:
        """Get and convert environment variable based on field type.

        Parameters
        ----------
        env_key : str
            Env variable key to get the value from.
        field_type : type
            Type to convert the env variable to.

        Returns
        -------
        Any
            The value of the env variable converted to the target type, or None if the env variable is not set.

        Raises
        ------
            ValueError if the env variable value could not be converted to the target type.
        """
        env_str = os.environ.get(env_key)
        if env_str is None:
            return None

        if field_type is bool:
            return env_str.lower() in ("1", "true", "yes", "on")
        elif field_type is int:
            return int(env_str)
        elif field_type is str:
            return env_str
        elif issubclass(field_type, IntEnum):
            try:
                return field_type(int(env_str))
            except ValueError:
                return field_type[env_str]
        else:
            return field_type(env_str)

    def get_env_variables(self) -> dict[str, Any]:
        """Return the env variables that are set and will influence these settings.

        Returns
        -------
        dict[str, Any]
            A dict from variable keys to values (with proper types).
        """
        vars = {}
        for field in fields(self):
            key = f"BL_{field.name.upper()}"
            val = self._get_env_value(key, field.type)

            if val is not None:
                vars[key] = val

        return vars

    def as_dict(self) -> dict[str, Any]:
        """Returns the settings as a dict."""
        # A bit more comfortable than having to import dataclasses.asdict each time
        return asdict(self)


def _update_settings(**overrides) -> None:
    """Replace the _SETTINGS object with a new instance with updated values. Only non-None values are applied.

    This should only be called right after the launch process has started.

    Parameters
    ----------
    overrides :
        Values to override. See [_Settings][] for valid keywords.
    """
    global _SETTINGS

    updates = {}
    for field in fields(_SETTINGS):
        if field.name not in overrides:
            continue

        value = overrides.get(field.name)
        if value is None:
            continue

        if issubclass(field.type, IntEnum):
            if isinstance(value, int):
                value = field.type(value)
            elif isinstance(value, str):
                value = field.type[value]

        updates[field.name] = value

    if updates:
        _SETTINGS = replace(_SETTINGS, **updates)


def Settings() -> _Settings:
    """Get the current settings.

    This function serves two purposes: 1. dissuades replacing the _SETTINGS object, and 2. ensures that importing modules always get the most recent state (instead of the state on import).

    Returns
    -------
    Settings
        The current settings.
    """
    return _SETTINGS


_SETTINGS = _Settings()
