"""The three dialogs every flow is built from: Choice (pick one), Ask (type
something), Result (what happened). Each is a card over the screen behind it."""

from __future__ import annotations

from typing import TypeVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static
from textual.widgets.option_list import Option

from keepgram.ui import touch
from keepgram.ui.widgets import KeyBar, SafeOptionList, TextInput

T = TypeVar("T")


class Card(ModalScreen[T]):
    """A dialog. Its long part (.fit: a note, a log) gives up rows when the
    window is short, so the card itself never scrolls and its title and its
    answers always show - on a phone with the keyboard up the card used to
    scroll its title away, the note had a scrollbar of its own beside the
    card's, and the options were left the last two rows (found 2026-11-03)."""

    def on_screen_resume(self) -> None:
        self._fit()

    def on_resize(self) -> None:
        self._fit()

    def _fit(self) -> None:
        for part in self.query(".fit"):
            part.styles.max_height = None  # its whole height first ...
            self.call_after_refresh(self._shrink, part)

    def _shrink(self, part) -> None:
        # ... then as many rows fewer as the card would have to scroll.
        over = self.query_one(".dialog").max_scroll_y
        if over > 0:
            part.styles.max_height = max(1, part.outer_size.height - over)


class Choice(Card[str | None]):
    """Pick one of `options` [(key, label)]; Esc gives None. `default` is the key
    highlighted when it opens - for a yes/no, the safe answer."""

    BINDINGS = [Binding("escape", "cancel", "Back")]

    def __init__(self, title: str, note: str, options: list[tuple[str, str]], default: str | None = None) -> None:
        super().__init__()
        self.title_text, self.note, self.options = title, note, options
        keys = [k for k, _ in options]
        self.default = keys.index(default) if default in keys else 0

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="dialog-title")
            if self.note:
                with VerticalScroll(classes="note-scroll fit"):
                    yield Static(self.note)
            yield SafeOptionList(*[Option(label, id=key) for key, label in self.options], default=self.default)
        yield KeyBar()

    def on_mount(self) -> None:
        self.query_one(SafeOptionList).focus()

    def on_option_list_option_selected(self, event: SafeOptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Ask(Card[str | None]):
    """Type one line; Enter gives it, Esc gives None. On a phone the mouse is let
    go while the box has the cursor, so a tap anywhere brings the keyboard."""

    BINDINGS = [Binding("escape", "cancel", "Back")]

    def __init__(self, title: str, note: str = "", value: str = "", password: bool = False,
                 placeholder: str = "") -> None:
        super().__init__()
        self.title_text, self.note, self.value = title, note, value
        self.password, self.placeholder = password, placeholder

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="dialog-title")
            if self.note:
                with VerticalScroll(classes="note-scroll fit"):
                    yield Static(self.note)
            yield TextInput(self.value, password=self.password, placeholder=self.placeholder)
            if touch.PHONE:
                yield Static("Keyboard gone? Tap anywhere.", classes="hint")
        yield KeyBar()

    def on_mount(self) -> None:
        self.query_one(TextInput).focus()

    def on_input_submitted(self, event: TextInput.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Result(Card[None]):
    """How it ended: the frame is green for done, red for failed."""

    BINDINGS = [Binding("escape,enter", "close", "OK")]

    def __init__(self, title: str, text: str, ok: bool = True) -> None:
        super().__init__()
        self.title_text, self.text, self.ok = title, text, ok

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog " + ("ok" if self.ok else "failed")):
            yield Label(self.title_text, classes="dialog-title")
            with VerticalScroll(id="result-text", classes="fit"):
                yield Static(self.text)
            yield Button("OK", variant="primary", id="ok")
        yield KeyBar()

    def on_mount(self) -> None:
        self.query_one("#ok", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
