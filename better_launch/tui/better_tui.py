import os
from typing import Literal, Callable
from enum import IntEnum, auto
import logging
import threading
import re
from dataclasses import dataclass

from prompt_toolkit import Application, print_formatted_text
from prompt_toolkit.output.color_depth import ColorDepth
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.application.current import get_app
from prompt_toolkit.layout.containers import HSplit, Window, ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import set_title

from better_launch import BetterLaunch
from better_launch.elements import (
    AbstractNode,
    ForeignNode,
    Component as ComponentNode,
    LifecycleStage,
)
import better_launch.ros.logging as roslog

from better_launch.tui.footer_menu import FooterMenu


class AppMode(IntEnum):
    """States of our TUI. The TUI decides what to display based on the active state.
    """
    # See BetterTui._switch_mode for details
    STANDARD = auto()
    CONFIRM_EXIT = auto()
    SEARCH_NODE = auto()
    NODE_MENU = auto()
    NODE_INFO = auto()
    NODE_LIFECYCLE = auto()
    CONFIRM_NODE_TAKEOVER = auto()
    CONFIRM_NODE_RESTART = auto()
    CONFIRM_NODE_KILL = auto()
    LOG_LEVEL = auto()
    NODE_LOG_LEVEL = auto()


@dataclass
class LogLevel:
    name: str
    level: int
    style: str


_log_levels = {
    "INFO": LogLevel("INFO", logging.INFO, "ansibrightgreen"),
    "WARNING": LogLevel("WARNING", logging.WARNING, "yellow"),
    "ERROR": LogLevel("ERROR", logging.ERROR, "ansibrightred"),
    "CRITICAL": LogLevel("CRITICAL", logging.CRITICAL, "ansibrightmagenta"),
    "DEBUG": LogLevel("DEBUG", logging.DEBUG, "ansibrightblue"),
    "MUTE": LogLevel("MUTE", 999, "grey"),
}


class NodeLogFilter(logging.Filter):
    def __init__(self, name: str = ""):
        super().__init__(name)
        self.muted: set[str] = set()
        self.hermit: str = None

    def mute(self, node: str) -> None:
        self.muted.add(node)
    
    def unmute(self, node: str) -> None:
        self.muted.discard(node)

    def set_hermit(self, node: str) -> None:
        self.hermit = node

    def clear(self) -> None:
        self.muted.clear()
        self.hermit = None

    def filter(self, record: logging.LogRecord) -> bool:
        if self.hermit:
            if record.name != self.hermit:
                return False

        elif record.name in self.muted:
            return False

        return super().filter(record)


# Custom level to block all output
logging.addLevelName(999, "MUTE")


class BetterTui:
    def __init__(
        self,
        launch_func: Callable[[], None],
        *,
        manage_foreign_nodes: bool = False,
        keep_alive: bool = False,
        color_depth: Literal[1, 4, 8, 24] = 8,
    ):
        """Our TUI class. Use [run][] to start the TUI.

        In order to override keybindings you may set the BL_TUI_KEYBINDS environment variable. For example, this will bind the nodes menu to ctrl-n and setting the log level to ctrl-l:

        .. code:: bash

            BL_TUI_KEYBINDS="nodes: c-n; loglevel: c-l" bl better_launch 02_ui.launch.py

        The syntax is always `<action>:<keys>` separated by `;`. The valid actions are `exit`, `mute`, `nodes`, `loglevel`, `cancel`, `enter`, `next`, `previous`. For valid key specifiers see `prompt_toolkit <https://python-prompt-toolkit.readthedocs.io/en/stable/pages/advanced_topics/key_bindings.html>`_. Take special note of how the Alt/Meta/Option key is treated. 

        Parameters
        ----------
        launch_func : Callable[[], None]
            The launch function to run once this TUI is started.
        manage_foreign_nodes : bool, optional
            Whether to list foreign nodes in the nodes menu.
        keep_alive : bool, optional
            If True, the TUI will keep running even when the last node stops running.
        color_depth : Literal[1, 4, 8, 24], optional
            How many colors to use for display. Corresponds to monochrome, ANSI colors, 256 colors, true colors.
        """
        self.launch_func = launch_func
        self.manage_foreign_nodes = manage_foreign_nodes
        self.keep_alive = keep_alive
        self.color_depth = {
            1: ColorDepth.DEPTH_1_BIT,
            4: ColorDepth.DEPTH_4_BIT,
            8: ColorDepth.DEPTH_8_BIT,
            24: ColorDepth.DEPTH_24_BIT,
        }[color_depth]

        self.history = InMemoryHistory()
        self.bindings = KeyBindings()

        # Allows the user to override keybindings. Keybindings as lists to support meta keys.
        # See https://python-prompt-toolkit.readthedocs.io/en/stable/pages/advanced_topics/key_bindings.html
        self.keybinds = {
            "exit": ["c-c"],
            "mute": ["space"],
            "nodes": ["tab"],
            "loglevel": ["x"],
            "cancel": ["escape"],
            "enter": ["enter"],
            "next": ["tab"],
            "previous": ["s-tab"],
        }

        # Keybind overrides
        alt_keybinds = os.environ.get("BL_TUI_KEYBINDS")
        if alt_keybinds:
            for item in alt_keybinds.split(";"):
                item = item.strip()
                if not re.match(r"[a-z_]+:\s*[\w ]+", item):
                    raise ValueError(f"Invalid keybind override {item}")
                
                action, keys = item.split(":", maxsplit=1)
                if action not in self.keybinds:
                    logging.getLogger().warning(f"Ignoring unknown keybind {action}")
                
                self.keybinds[action] = keys.strip().split(" ")

        # Make the key combinations in our footer show up a little nicer
        default_footer_text = " \x1b[38;5;208m{exit}\x1b[0m Quit  \x1b[38;5;208m{mute}\x1b[0m Mute  \x1b[38;5;208m{nodes}\x1b[0m Nodes  \x1b[38;5;208m{loglevel}\x1b[0m Log Level"

        keys_print = {}
        for action, keys in self.keybinds.items():
            # We only show the first key (or two in case of meta + key, see below)
            k = keys[0]
            
            # Control as ^X
            if k.startswith("c-"):
                k = "^" + k[2].upper() + k[3:]
            # Meta as M-
            elif k == "escape" and len(keys) > 1:
                # Represented as escape + a key stroke in prompt_toolkit
                k = "M-" + keys[1][0].upper() + keys[1][1:]
            else:
                k = k[0].upper() + k[1:]

            keys_print[action] = k

        self.default_footer_text = ANSI(default_footer_text.format(**keys_print))

        self.mode = AppMode.STANDARD
        self.footer_text: str = self.default_footer_text
        self.nodes_snapshot: list[AbstractNode] = []
        self.selected_node: AbstractNode = None

        self.prev_log_level = _log_levels["MUTE"]
        self.log_level = _log_levels["INFO"]
        self.muted = False

        self.title: FormattedTextControl = None
        self.footer_window: Window = None
        self.search_field: TextArea = None
        self.search_buffer: Buffer = None
        self.footer_menu: FooterMenu = None

        # Allows us to have more control over what is showing
        self.log_filter = NodeLogFilter()

        self._setup_key_bindings()

    def run(self):
        """Initialize the TUI app, then run the launch function before starting the TUI.
        """
        layout = self._make_layout()
        app = Application(
            layout=layout,
            key_bindings=self.bindings,
            full_screen=False,
            color_depth=self.color_depth,
            cursor=CursorShape.BLOCK,
        )

        def _run_launch_func() -> None:
            """Runs the launch function passed to the constructor and sets up the log capturing mechanism."""
            self.launch_func()

            # Doing this earlier will mess up screen output somehow
            log_handler: logging.Handler = roslog.launch_config.get_screen_handler()
            log_handler.addFilter(self.log_filter)

            bl = BetterLaunch.wait_for_instance()
            set_title(os.path.basename(bl.launchfile))
            bl.spin(exit_with_last_node=not self.keep_alive)
            self.quit("launch function exited")

        launch_thread = threading.Thread(target=_run_launch_func)

        with patch_stdout(raw=True):
            launch_thread.start()
            app.run()

    def quit(self, reason: str) -> None:
        """Shutdown better_launch if it is still running, then exit the TUI.

        Parameters
        ----------
        reason : str
            A reason for the shutdown that will be shown to the user.
        """
        bl = BetterLaunch.instance()
        if bl:
            try:
                bl.shutdown(reason)
            except Exception as e:
                print(e)

        try:
            get_app().exit()
        except Exception:
            # Might already have exited
            pass

    # Some common helpers
    def _is_footer_visible(self) -> bool:
        """Whether the footer line should be visible.
        """
        return self.mode not in (AppMode.SEARCH_NODE,)

    def _is_search_visible(self) -> bool:
        """Whether the search bar should be visible.
        """
        return self.mode in (AppMode.SEARCH_NODE,)

    def _is_menu_visible(self) -> bool:
        """Whether the menu widget should be visible.
        """
        return self.mode not in (
            AppMode.STANDARD,
            AppMode.NODE_INFO,
        )

    def _get_matching_node_items(self, filter: str) -> list[tuple[str, str, AbstractNode]]:
        """Check which node items in the current node snapshot match the provided filter string.

        Parameters
        ----------
        filter : str
            A string that will be looked for in each nodes' full name.

        Returns
        -------
        list[tuple[str, str, AbstractNode]]
            The style, short name, and node for each node that matched the filter string.
        """
        filter = filter.lower()
        ret = []

        for n in self.nodes_snapshot:
            if filter in n.fullname.lower():
                style = "green" if n.is_running else "red"
                ret.append((style, n.name, n))

        return ret

    def _set_log_level(self, level: LogLevel) -> None:
        """Configure the severity level that our logger will output on the terminal.

        Parameters
        ----------
        level : LogLevel
            The new minimum severity level.
        """
        self.prev_log_level = self.log_level
        self.log_level = level
        handler: logging.Handler = roslog.launch_config.get_screen_handler()
        handler.setLevel(level.level)

    def _menu_cancel(self) -> None:
        """Hide any open menu by returning to STANDARD mode.
        """
        self._switch_mode(AppMode.STANDARD)
        get_app().layout.focus(self.footer_window)

    # Setup user interactions
    def _setup_key_bindings(self) -> None:
        """Setup the key bindings. This is how the user will interact with the TUI and usually results in calls to [_switch_mode` or :meth:`_handle_menu_accept][].
        """
        bind = self.bindings.add

        mode_standard = Condition(lambda: self.mode == AppMode.STANDARD)
        menu_visible = Condition(self._is_menu_visible)


        @bind(*self.keybinds["exit"])
        async def _(event: KeyPressEvent):
            self._switch_mode(AppMode.CONFIRM_EXIT)

        @bind(*self.keybinds["mute"], filter=~Condition(self._is_search_visible))
        def _(event: KeyPressEvent):
            self.muted = not self.muted
            level = _log_levels["MUTE"] if self.muted else self.prev_log_level
            self._set_log_level(level)

        @bind(*self.keybinds["nodes"], filter=mode_standard)
        def _(event: KeyPressEvent):
            self._switch_mode(AppMode.SEARCH_NODE)

        @bind(*self.keybinds["loglevel"], filter=mode_standard)
        def _(event: KeyPressEvent):
            self._switch_mode(AppMode.LOG_LEVEL)

        # Menu interactions
        @bind(*self.keybinds["cancel"], filter=menu_visible, eager=True)
        def _(event: KeyPressEvent):
            self._switch_mode(AppMode.STANDARD)

        @bind(*self.keybinds["enter"], filter=menu_visible)
        def _(event: KeyPressEvent):
            if not self.footer_menu.items:
                self._menu_cancel()
            else:
                self._handle_menu_accept(self.footer_menu.selected)

        @bind(*self.keybinds["next"], filter=menu_visible)
        def _(event: KeyPressEvent):
            self.footer_menu.select_next()

        @bind(*self.keybinds["previous"], filter=menu_visible)
        def _(event: KeyPressEvent):
            self.footer_menu.select_prev()

        for i in range(10):

            @bind(
                str(i),
                filter=menu_visible
                & ~Condition(self._is_search_visible)
                & Condition(lambda k=i: k < len(self.footer_menu.items)),
            )
            def _(event: KeyPressEvent):
                self.footer_menu.select((i - 1) % 10)
                self._handle_menu_accept(self.footer_menu.selected)

    def _switch_mode(self, mode: AppMode) -> None:
        """The TUI basically uses a statemachine to decide what to show in the bottom menu. This function transitions the TUI into a new state.

        Parameters
        ----------
        mode : AppMode
            The state to transition to.
        """
        self.mode = mode

        if mode == AppMode.STANDARD:
            self.selected_node = None
            self.footer_text = self.default_footer_text

        elif mode == AppMode.CONFIRM_EXIT:
            self.footer_text = "Shutdown nodes and quit?"
            self.footer_menu.set_items(["yes", "no"])

        elif mode == AppMode.SEARCH_NODE:
            self.footer_text = ""

            bl = BetterLaunch.instance()
            self.nodes_snapshot = bl.get_nodes(
                include_components=True,
                include_launch_service=True,
                include_foreign=self.manage_foreign_nodes,
            )

            items = self._get_matching_node_items("")
            self.footer_menu.set_items(items)

            self.search_buffer.text = ""
            get_app().layout.focus(self.search_field)

        elif mode == AppMode.NODE_MENU:
            # Contains the format, node name, and a reference to the AbstractNode
            # (see SEARCH_NODE above)
            item = self.footer_menu.get_selected_item()
            node = item[2]
            self.selected_node = node

            choices = ["info", "log level"]
            if node.is_running:
                if node.is_lifecycle_node():
                    choices.append("lifecycle")

                if isinstance(node, ForeignNode):
                    choices.append("takeover")
                elif isinstance(node, ComponentNode):
                    choices.extend(["restart", "unload"])
                else:
                    choices.extend(["restart", "kill"])
            else:
                choices.append("start")

            self.footer_text = node.fullname
            self.footer_menu.set_items(choices)

        elif mode == AppMode.NODE_INFO:
            # Simply print to our captured stdout
            cols = get_app().output.get_size().columns
            bar = "\n" + "=" * cols + "\n"
            # NOTE we should not use html formatting as some node params may be html-like
            text = self.selected_node.get_info_sheet()
            print_formatted_text(bar, "\n", ANSI(text), bar)

            self._menu_cancel()

        elif mode == AppMode.NODE_LIFECYCLE:
            self.footer_text = "Choose target state for " + self.selected_node.fullname

            valid_stages = list([s.name for s in LifecycleStage])
            active = valid_stages.index(self.selected_node.lifecycle.current_stage.name)
            self.footer_menu.set_items(valid_stages, active)

        elif mode == AppMode.CONFIRM_NODE_TAKEOVER:
            self.footer_text = f"Restart {self.selected_node.fullname} for takeover?"
            self.footer_menu.set_items(["yes", "no"])

        elif mode == AppMode.CONFIRM_NODE_RESTART:
            self.footer_text = f"Restart {self.selected_node.fullname}?"
            self.footer_menu.set_items(["yes", "no"])

        elif mode == AppMode.CONFIRM_NODE_KILL:
            self.footer_text = f"Terminate {self.selected_node.fullname}?"
            self.footer_menu.set_items(["yes", "no"])

        elif mode == AppMode.LOG_LEVEL:
            self.footer_text = "Select log level"
            levels = list(_log_levels.values())
            items = [(lev.style, lev.name) for lev in levels]
            active = levels.index(self.log_level)
            self.footer_menu.set_items(items, active)

        elif mode == AppMode.NODE_LOG_LEVEL:
            self.footer_text = f"Node {self.selected_node.fullname}"
            self.footer_menu.set_items(["mute", "mute others", "unmute", "unmute all"])

    def _handle_menu_accept(self, idx: int) -> None:
        """Decide what to do when a menu item is activated by the user. Usually this will result in a state transition (via [_switch_mode][]) and some side effects.

        Parameters
        ----------
        idx : int
            Index of the activated menu item.
        """
        item = self.footer_menu.get_selected_item()

        if self.mode == AppMode.CONFIRM_EXIT:
            if item == "yes":
                self.quit("user request")
                return

            self._menu_cancel()

        elif self.mode == AppMode.SEARCH_NODE:
            self._switch_mode(AppMode.NODE_MENU)
            # Don't cancel the menu here

        elif self.mode == AppMode.NODE_MENU:
            action = self.footer_menu.get_selected_item()

            if action == "info":
                self._switch_mode(AppMode.NODE_INFO)

            if action == "log level":
                self._switch_mode(AppMode.NODE_LOG_LEVEL)

            elif action == "lifecycle":
                self._switch_mode(AppMode.NODE_LIFECYCLE)

            elif action == "takeover":
                self._switch_mode(AppMode.CONFIRM_NODE_TAKEOVER)

            elif action == "restart":
                self._switch_mode(AppMode.CONFIRM_NODE_RESTART)

            elif action in ("kill", "unload"):
                self._switch_mode(AppMode.CONFIRM_NODE_KILL)

            elif action == "start":
                # No confirmation needed here
                self.selected_node.start()
                self._menu_cancel()

            else:
                self._menu_cancel()

        elif self.mode == AppMode.NODE_LIFECYCLE:
            target_stage = LifecycleStage[item]
            self.selected_node.lifecycle.transition(target_stage)
            self._menu_cancel()

        elif self.mode == AppMode.CONFIRM_NODE_TAKEOVER:
            if item == "yes":
                self.selected_node.takeover(kill_after=3.0)
            self._menu_cancel()

        elif self.mode == AppMode.CONFIRM_NODE_RESTART:
            if item == "yes":
                self.selected_node.shutdown("restarting node", timeout=None)
                self.selected_node.start()
            self._menu_cancel()

        elif self.mode == AppMode.CONFIRM_NODE_KILL:
            if item == "yes":
                self.selected_node.shutdown("terminated by user")
            self._menu_cancel()

        elif self.mode == AppMode.LOG_LEVEL:
            if isinstance(item, tuple):
                item = item[1]

            level = _log_levels[item]
            self._set_log_level(level)
            self._menu_cancel()

        elif self.mode == AppMode.NODE_LOG_LEVEL:
            node = self.selected_node.fullname

            if item == "mute":
                self.log_filter.mute(node)
            elif item == "mute others":
                self.log_filter.set_hermit(node)
            elif item == "unmute":
                self.log_filter.unmute(node)
            elif item == "unmute all":
                self.log_filter.clear()
            self._menu_cancel()

    def _make_layout(self) -> Layout:
        """Creates our TUI's layout. Even though we run in "stdout mode", the lines we occupy still count as widgets.

        Returns
        -------
        Layout
            The layout to be used by the app.
        """

        def on_search_update(_) -> None:
            new_text = self.search_buffer.text
            matches = self._get_matching_node_items(new_text)
            self.footer_menu.update_items(matches)

        self.title = FormattedTextControl("")
        self.footer_window = Window(FormattedTextControl(lambda: self.footer_text))

        self.search_field = TextArea(
            prompt="Search: ",
            height=1,
            multiline=False,
            wrap_lines=False,
        )
        self.search_buffer = self.search_field.buffer
        self.search_buffer.on_text_changed += on_search_update

        self.footer_menu = FooterMenu([])

        footer_visible = Condition(self._is_footer_visible)
        search_visible = Condition(self._is_search_visible)
        menu_visible = Condition(self._is_menu_visible)

        return Layout(
            HSplit(
                [
                    Window(self.title, height=1),
                    ConditionalContainer(
                        self.footer_window,
                        footer_visible,
                    ),
                    ConditionalContainer(
                        self.search_field,
                        search_visible,
                    ),
                    ConditionalContainer(
                        Window(self.footer_menu, height=1),
                        menu_visible,
                    ),
                ]
            )
        )
