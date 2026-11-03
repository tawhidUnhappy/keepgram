"""The full-screen menus, built on Textual like remanga's.

One screen at a time, the same layout everywhere: where you are at the top,
the list or dialog in the middle, the keys at the bottom (click them too). The
mouse works throughout: the wheel scrolls, a click highlights a row, a double
click chooses it. Work runs in a task screen and ends on a result."""

from __future__ import annotations

import asyncio
import logging

from textual.app import App

from keepgram import config
from keepgram.ui import look, touch
from keepgram.ui.dialogs import Result
from keepgram.ui.screens import HomeScreen
from keepgram.ui.task import TaskScreen

CSS = """
Screen { background: $background; }
#home { height: auto; max-height: 1fr; border: none; padding: 0 1; background: $background; }
#home > .option-list--option { padding: 0 1; }
SafeTable { height: 1fr; background: $background; }
SafeTable > .datatable--header { background: $background; color: $primary; text-style: bold; }

.dialog {
    width: 80; max-width: 95%; height: auto; max-height: 100%;
    padding: 1 2; background: $surface; border: none;
    overflow-y: auto; scrollbar-size-vertical: 1;
}
.dialog.ok .dialog-title { color: $success; }
.dialog.failed .dialog-title { color: $error; }
Result, Choice, Ask { align: center middle; background: $background 60%; }
.dialog-title { text-style: bold; margin-bottom: 1; color: $primary; }
.note { color: $text-muted; margin-bottom: 1; }
.hint { color: $text-muted; }
/* As tall as they need: a short window takes rows off them, not the card (dialogs.Card). */
.note-scroll { height: auto; color: $text-muted; margin-bottom: 1; background: $surface;
               scrollbar-size-vertical: 1; }
#result-text { height: auto; background: $surface; scrollbar-size-vertical: 1; }
.dialog SafeOptionList { height: auto; border: none; padding: 0; background: $surface; }
.dialog Input { margin-top: 1; }
.dialog Button { margin-top: 1; }

.task { height: 1fr; padding: 0 2; margin: 0 1; background: $surface; }
#step { margin-bottom: 1; width: 100%; text-wrap: nowrap; text-overflow: ellipsis; }
#bar-row { height: 1; }
#bar-label { width: auto; max-width: 45%; margin-right: 2; color: $text-muted; text-wrap: nowrap;
             text-overflow: ellipsis; }
/* Not "#bar": that is the id of the strip inside every Textual ProgressBar, and a
   min-width meant for the whole bar pushed its % under the size beside it. */
#file-bar { width: 1fr; min-width: 8; }
#file-bar Bar, #all-bar Bar { width: 1fr; }
#bar-detail { width: auto; color: $text-muted; margin-left: 1; text-wrap: nowrap; }
#all-row { height: 1; margin-top: 1; }
#all-label { width: auto; margin-right: 2; color: $primary; text-style: bold; }
#all-bar { width: 1fr; min-width: 8; }
#all-detail { color: $text-muted; }
#output { height: 1fr; min-height: 3; margin: 1 0; color: $text-muted; background: $background;
          overflow-x: hidden; scrollbar-size-vertical: 1; padding: 0 1; }

/* A phone: narrow held upright, short with its keyboard up or turned sideways. The
   spacing goes, so the log and the notes get the rows. */
Screen.-narrow .dialog { max-width: 100%; padding: 1 1; }
Screen.-narrow .task { padding: 0 1; margin: 0; }
Screen.-narrow #bar-label { max-width: 35%; }
Screen.-short TopBar { margin-bottom: 0; }
Screen.-short .dialog { padding: 0 1; }
Screen.-short .dialog-title { margin-bottom: 0; }
Screen.-short .dialog Input { margin-top: 0; }
Screen.-short .dialog Button { margin-top: 0; height: 1; border: none; }
Screen.-short #step { margin-bottom: 0; }
Screen.-short #all-row { margin-top: 0; }
Screen.-short #output { margin: 0; }
"""


def normal_tasks() -> None:
    """Undo Textual's eager tasks before anything talks to Telegram.

    App.run() (a real terminal - not the headless test mode) sets
    asyncio.eager_task_factory on the loop. Telethon starts its send and receive
    loops with create_task inside connect() and marks itself connected only
    after: an eager task runs at once, sees "not connected" and ends - so not
    one request is ever sent and connect() hangs. Found 2026-11-02: the menus
    sat at "not logged in" forever in a real terminal."""
    asyncio.get_running_loop().set_task_factory(None)


class KeepgramApp(App):
    CSS = CSS
    TITLE = "keepgram"
    ENABLE_COMMAND_PALETTE = False
    # The classes the stylesheet's phone rules go by: a phone held upright is
    # under 70 columns; with its keyboard up, or sideways, it's under 28 rows.
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (70, "-wide")]
    VERTICAL_BREAKPOINTS = [(0, "-short"), (28, "-tall")]

    def __init__(self) -> None:
        super().__init__()
        self.cfg = config.load()
        self.client = None
        self.me = None
        look.register(self)
        self.theme = self.cfg.get("menus", {}).get("look", "keepgram-dark")
        # Telegram's notices go to the task screen, never onto the terminal.
        logging.getLogger().addHandler(logging.NullHandler())

    def on_mount(self) -> None:
        normal_tasks()
        if touch.PHONE:
            # Mouse or keyboard, whichever the moment wants (touch.py): checked
            # often, so it never matters which way a screen or a box went away.
            self.set_interval(0.25, lambda: touch.sync(self))
        self.push_screen(HomeScreen())

    def start_flow(self, coro) -> None:
        """Run a flow (dialogs and tasks one after the other) as a worker; an
        error ends on a Result instead of closing the menus."""

        normal_tasks()

        async def guarded():
            try:
                await coro
            except SystemExit as e:
                await self.push_screen_wait(Result("Can't do that", str(e.code), ok=False))
            except Exception as e:
                await self.push_screen_wait(Result("Something went wrong", f"{type(e).__name__}: {e}", ok=False))

        self.run_worker(guarded(), group="flow", exit_on_error=False)

    async def action_quit(self) -> None:
        if isinstance(self.screen, TaskScreen):
            self.notify("Still working - press Ctrl+C to stop it first.", severity="warning")
            return
        if self.client is not None:
            await self.client.disconnect()
        self.exit()
