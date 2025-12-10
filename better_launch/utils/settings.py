import os
import logging
import enum
from dataclasses import dataclass


class Colormode(enum.IntEnum):
    # Color messages based on their severity and highlight the sources in one color
    DEFAULT = 0

    # Color messages only based on their severity
    SEVERITY = 1

    # Color messages only based on the logging source
    SOURCE = 2

    # Don't color messages
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


# TODO make this a singleton somehow
@dataclass
class _Settings:
    __ui: bool = False
    __colormode: Colormode = Colormode.DEFAULT
    __print_limit: int = 0
    __screen_log_level: int = logging.INFO
    __screen_log_format: str = default_screen_format
    __file_log_level: int = logging.INFO
    __file_log_format: str = default_file_format

    __initialized = False

    def _initialize(
        self,
        ui: bool,
        colormode: Colormode,
        print_limit: int,
        screen_log_level: int,
        screen_log_format: str,
        file_log_level: int,
        file_log_format: str,
    ) -> None:
        """For all overrides the priority is `CLI > ENV > launchfile`.
        """
        if self.__initialized:
            raise RuntimeError("Settings cannot be initialized again")

        # Whether to start the TUI
        env_ui = os.environ.get("BL_UI_OVERRIDE")
        if env_ui:
            self.__ui = (env_ui.lower() == "true")
        else:
            self.__ui = ui

        # Logging colormode
        env_colormode = os.environ.get("BL_COLORMODE")
        if env_colormode:
            try:
                colormode = int(env_colormode)
            except ValueError:
                colormode = env_colormode
        
        if isinstance(colormode, str):
            self.__colormode = Colormode[colormode.upper()]
        else:
            # Also works for IntEnum members
            self.__colormode = Colormode(colormode)

        # Limits the lengths of printed messages
        env_print_limit = os.environ.get("BL_PRINT_LIMIT")
        if env_print_limit:
            self.__print_limit = int(env_print_limit)
        else:
            self.__print_limit = print_limit

        # Log levels
        env_screen_level = os.environ.get("BL_SCREEN_LOG_LEVEL")
        if env_screen_level:
            try:
                screen_log_level = int(env_screen_level)
            except ValueError:
                screen_log_level = env_screen_level
        elif isinstance(screen_log_level, str):
            screen_log_level = severity_to_loglevel(screen_log_level)
        
        self.__screen_log_level = screen_log_level

        env_file_level = os.environ.get("BL_file_LOG_LEVEL")
        if env_file_level:
            try:
                file_log_level = int(env_file_level)
            except ValueError:
                file_log_level = env_file_level
        elif isinstance(file_log_level, str):
            file_log_level = severity_to_loglevel(file_log_level)

        self.__file_log_level = file_log_level

        # Log formats
        env_screen_format = os.environ.get("BL_SCREEN_LOG_FORMAT")
        if env_screen_format:
            self.__screen_log_format = env_screen_format
        else:
            self.__screen_log_format = screen_log_format

        env_file_format = os.environ.get("BL_FILE_LOG_FORMAT")
        if env_file_format:
            self.__file_log_format = env_file_format
        else:
            self.__file_log_format = file_log_format

        self.__initialized = True

    @property
    def ui(self) -> bool:
        return self.__ui

    @property
    def colormode(self) -> Colormode:
        return self.__colormode

    @property
    def print_limit(self) -> int:
        return self.__print_limit

    @property
    def screen_log_level(self) -> int:
        return self.__screen_log_level

    @property
    def screen_log_format(self) -> str:
        return self.__screen_log_format

    @property
    def file_log_level(self) -> int:
        return self.__file_log_level

    @property
    def file_log_format(self) -> str:
        return self.__file_log_format


SETTINGS = _Settings()
