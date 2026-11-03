"""Textual widgets for keepgram's menus.

A list opens with a row already highlighted, so Enter works straight away (the
user's call, 2026-11-02 - remanga's "nothing until you press an arrow" made
the menu look broken). Lists that ask yes/no open on the SAFE answer instead
(Choice's `default`), so a stray Enter never starts a big job. Enter or a
DOUBLE click chooses; a single click only moves the highlight."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input, OptionList, Static

PATH_SEPARATOR = "  ›  "


def _path_text(path: list[str], width: int) -> Text:
    """The path, as much as fits: the place you are in stays whole longest,
    the places above it collapse to "…" first."""
    parts = list(path)
    for collapse in range(len(parts)):
        shown = ["…" if 0 < i <= collapse and i < len(parts) - 1 else part for i, part in enumerate(parts)]
        if len(PATH_SEPARATOR.join(shown)) <= width or collapse >= len(parts) - 2:
            parts = shown
            break
    text = Text()
    for i, part in enumerate(parts):
        if i:
            text.append(PATH_SEPARATOR, style="dim")
        text.append(part, style="bold" if i == len(parts) - 1 else "dim")
    text.truncate(max(1, width), overflow="ellipsis")
    return text


class TopBar(Static):
    """Where you are, and a short fact beside it (or below, when it won't fit)."""

    DEFAULT_CSS = """
    TopBar { dock: top; height: auto; padding: 0 1; background: $surface; margin-bottom: 1; }
    """

    def __init__(self, path: list[str], info: str = "") -> None:
        super().__init__()
        self.path, self._info = path, info

    def on_mount(self) -> None:
        self._draw()

    def on_resize(self) -> None:
        self._draw()

    def set_info(self, info: str) -> None:
        self._info = info
        self._draw()

    def _draw(self) -> None:
        if not self.is_attached:
            return
        width = self.content_region.width or self.app.size.width - 2
        full = PATH_SEPARATOR.join(self.path)
        info = Text(self._info, style="dim")
        if not self._info:
            self.update(_path_text(self.path, width))
        elif len(full) + 3 + len(self._info) <= width:
            line = _path_text(self.path, width)
            line.append(" " * (width - len(full) - len(self._info)))
            self.update(line + info)
        else:
            self.update(Text("\n").join([_path_text(self.path, width), info]))


class KeyBar(Static):
    """The keys this screen takes, wrapped onto as many lines as the window
    needs so no key falls off the edge. Click one to press it."""

    DEFAULT_CSS = """
    KeyBar { dock: bottom; height: auto; padding: 0 1; background: $surface; }
    """

    def on_mount(self) -> None:
        self.screen.bindings_updated_signal.subscribe(self, self._bindings_changed)
        self.call_after_refresh(self._draw)

    def on_unmount(self) -> None:
        self.screen.bindings_updated_signal.unsubscribe(self)

    def on_resize(self) -> None:
        self._draw()

    def _bindings_changed(self, screen) -> None:
        if self.is_attached and screen is self.screen:
            self.call_after_refresh(self._draw)

    def _items(self) -> list[Text]:
        colours = self.app.theme_variables
        key_style = Style(color=colours.get("footer-key-foreground"), bold=True)
        label_style = Style(color=colours.get("footer-description-foreground"))
        seen, items = set(), []
        for _node, binding, enabled, _tooltip in self.screen.active_bindings.values():
            if not binding.show or binding.action in seen:
                continue
            seen.add(binding.action)
            item = Text.assemble((self.app.get_key_display(binding), key_style), " ",
                                 (binding.description, label_style))
            if not enabled:
                item.stylize("dim")
            item.stylize(Style(meta={"@click": f"app.simulate_key({binding.key.split(',')[0]!r})"}))
            items.append(item)
        return items

    def _draw(self) -> None:
        if not self.is_attached:
            return
        width = max(1, self.content_region.width or self.app.size.width - 2)
        lines: list[Text] = []
        line = Text()
        for item in self._items():
            item.truncate(width, overflow="ellipsis")
            if line and line.cell_len + 2 + item.cell_len > width:
                lines.append(line)
                line = Text()
            if line:
                line.append("  ")
            line.append_text(item)
        lines.append(line)
        self.update(Text("\n").join(lines))


class SafeTable(DataTable):
    """A table of rows: the first highlighted as soon as there are rows, Enter
    or a double click chooses."""

    BINDINGS = [Binding("enter", "select_cursor", "Choose")]

    def __init__(self, **kwargs) -> None:
        super().__init__(cursor_type="row", show_cursor=True, zebra_stripes=False, **kwargs)

    @property
    def picked_row(self) -> int | None:
        return self.cursor_row if self.row_count else None

    async def _on_click(self, event: events.Click) -> None:
        meta = event.style.meta
        row = meta.get("row")
        if row is None or row < 0 or meta.get("out_of_bounds", False):
            return
        event.prevent_default()
        event.stop()
        self.cursor_coordinate = Coordinate(row, 0)
        if event.chain >= 2:
            self.action_select_cursor()


class SafeOptionList(OptionList):
    """A list of choices: `default` (the first, unless said) highlighted when it
    opens, so Enter works at once; a double click chooses."""

    BINDINGS = [Binding("enter", "select", "Choose")]

    def __init__(self, *options, default: int = 0, **kwargs) -> None:
        super().__init__(*options, **kwargs)
        self.default = default

    def on_mount(self) -> None:
        if self.option_count:
            self.highlighted = min(max(self.default, 0), self.option_count - 1)

    async def _on_click(self, event: events.Click) -> None:
        event.prevent_default()
        clicked = event.style.meta.get("option")
        if clicked is None or self._options[clicked].disabled:
            return
        self.highlighted = clicked
        if event.chain >= 2:
            self.action_select()


class TextInput(Input):
    BINDINGS = [Binding("enter", "submit", "OK")]


class WrapLog(VerticalScroll):
    """Lines of output, wrapped to the window's width now (and again on every
    resize); follows the end while scrolled to it."""

    DEFAULT_CSS = """
    WrapLog > Static { width: 1fr; height: auto; }
    """

    def __init__(self, *, max_lines: int | None = None, id: str | None = None) -> None:
        super().__init__(id=id)
        self.max_lines = max_lines
        self._lines: list[Text] = []
        self._pending = False

    def compose(self):
        yield Static()

    def write(self, line: Text | str) -> None:
        self._lines.append(line if isinstance(line, Text) else Text(line))
        if self.max_lines and len(self._lines) > self.max_lines:
            del self._lines[:-self.max_lines]
        if not self._pending:
            self._pending = True
            self.call_after_refresh(self._show)

    def _show(self) -> None:
        self._pending = False
        if not self.is_attached:
            return
        following = self.scroll_y >= self.max_scroll_y - 1
        self.query_one(Static).update(Text("\n").join(self._lines))
        if following:
            self.call_after_refresh(self.scroll_end, animate=False)
