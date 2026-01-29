from typing import Any
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.application.current import get_app


class FooterMenu(FormattedTextControl):
    def __init__(
        self,
        items: list[str | tuple] = None,
        *,
        empty_prompt: str = "---",
        ellipses: str = "…",
        highlight_style: str = "reverse",
    ):
        """Creates a single line of selectable items. This allows to have menus without needing more space for drawing submenus. Items that don't fit into the line will be "scrolled" to as the selection shifts.

        Parameters
        ----------
        items : list[str  |  tuple[str]], optional
            The items to display. Items can be strings or tuples but don't have to be consistent. If an item is a tuple, the first element is the style of the item and the second element its label. Additional elements are ignored and can be used to store additional information with each item.
        empty_prompt : str, optional
            What to show when there are no items.
        ellipses : str, optional
            A character or string to signify that there are additional items.
        highlight_style : str, optional
            The style to use for showing that an item is selected.
        """
        super().__init__(self.render, focusable=False)

        self.items = items or []
        self.selected = 0
        self.empty_prompt = empty_prompt
        self.ellipses = ellipses
        self.highlight_style = highlight_style

    def render(self):
        if not self.items:
            return "---"

        cols = get_app().output.get_size().columns
        segments = []

        for i, txt in enumerate(self.items):
            if isinstance(txt, tuple):
                style, txt, *_ = txt
            else:
                style = ""
            
            if i == self.selected:
                style += " " + self.highlight_style

            segments.append((style, f" {txt} "))

        # fits?
        if sum(len(s[1]) for s in segments) <= cols:
            return segments

        ell = ("", self.ellipses)
        budget = cols - 2 * len(ell[1])
        shown = [segments[self.selected]]
        used = len(segments[self.selected][1])
        left, right = self.selected - 1, self.selected + 1

        while True:
            added = False
            if left >= 0 and used + len(segments[left][1]) <= budget:
                shown.insert(0, segments[left])
                used += len(segments[left][1])
                left -= 1
                added = True

            if right < len(segments) and used + len(segments[right][1]) <= budget:
                shown.append(segments[right])
                used += len(segments[right][1])
                right += 1
                added = True

            if not added:
                break

        if left >= 0:
            shown.insert(0, ell)

        if right < len(segments):
            shown.append(ell)

        return shown

    def select_next(self) -> None:
        """Select the next menu item, wrapping around.
        """
        self.selected = (self.selected + 1) % len(self.items)
        get_app().invalidate()

    def select_prev(self) -> None:
        """Select the previous menu item, wrapping around.
        """
        self.selected = (self.selected - 1) % len(self.items)
        get_app().invalidate()

    def select(self, idx: int) -> None:
        """Select the specified existing menu item. No modulo operation is performed on the passed index, so it must be valid.

        Parameters
        ----------
        idx : int
            The index of the item to be selected.

        Raises
        ------
        ValueError
            If the provided index is outside the range of items in this menu.
        """
        if not 0 <= idx < len(self.items):
            raise ValueError(
                f"Item index out of range (idx={idx}, len={len(self.items)})"
            )

        self.selected = idx
        get_app().invalidate()

    def get_selected_item(self) -> str | tuple:
        """Return the currently selected item data. If the item is a tuple it will have formatting in the first slot, its string representation in the second, and any additional information in subsequent slots.

        Returns
        -------
        str | tuple
            The item as it was passed to this menu.
        """
        return self.items[self.selected]

    def set_items(self, items: list[str | tuple[str, str]], default: int = 0) -> None:
        """Replace the items currently in this menu.

        Parameters
        ----------
        items : list[str | tuple[str, str]]
            The new items to use. If an item is a tuple, its first slot must be a formatting string and the second its string information. Any subsequent slots are kept, but ignored.
        default : int, optional
            Index of the item to select.
        """
        self.items = items
        self.selected = default
        get_app().invalidate()

    def update_items(self, items: list[str | tuple[str, str]]) -> None:
        """Like [FooterMenu.set_items][], except that it keeps the currently selected index intact if it is contained within the new list of items.

        Parameters
        ----------
        items : list[str | tuple[str, str]]
            The new items to use. If an item is a tuple, its first slot must be a formatting string and the second its string information. Any subsequent slots are kept, but ignored.
        """
        if self.selected >= len(items):
            self.selected = 0

        self.items = items
        get_app().invalidate()
