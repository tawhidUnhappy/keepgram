"""Work behind a task screen: the steps it has done, a progress bar for the
file being moved, and everything it prints, as it happens.

The work is a coroutine on the menus' own event loop - the same one Telegram
runs on. Ctrl+C asks it to stop after the current file (every keepgram job
checks between files, and running it again picks up where it stopped); a
second Ctrl+C stops at once. The screen is dismissed with an Outcome."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Label, ProgressBar

from keepgram import media
from keepgram.media import human
from keepgram.meter import duration
from keepgram.ui import touch
from keepgram.ui.widgets import KeyBar, KeyboardBox, TopBar, WrapLog


@dataclass
class Outcome:
    ok: bool
    value: Any = None
    error: str = ""
    stopped: bool = False


class Task:
    """What the work gets: say what it's doing, and ask whether to stop."""

    def __init__(self, screen: TaskScreen) -> None:
        self._screen = screen
        self.stopped = False

    def step(self, text: str) -> None:
        self._screen.step_text = text

    def log(self, text: str) -> None:
        self._screen.write(text)

    def cancelled(self) -> bool:
        return self.stopped


class _ToTask(logging.Handler):
    """Telegram's "wait N seconds" notices, into the task's output."""

    def __init__(self, screen: TaskScreen) -> None:
        super().__init__(logging.INFO)
        self.screen = screen

    def emit(self, record: logging.LogRecord) -> None:
        self.screen.write(f"[telegram] {record.getMessage()}")


class TaskScreen(Screen[Outcome]):
    BINDINGS = [Binding("ctrl+c", "stop", "Stop", priority=True)]

    def __init__(self, path: list[str], title: str, work: Callable[[Task], Awaitable[Any]]) -> None:
        super().__init__()
        self.path, self.title_text, self.work = path, title, work
        self.job = Task(self)
        self.step_text = "starting ..."
        self.bar: tuple[str, int, int] | None = None
        self.started = time.monotonic()
        self.worker = None
        self._handler = _ToTask(self)
        # Lines from any thread (hashing and joining run in one), shown on the next refresh.
        self._pending: list[str] = []

    def compose(self) -> ComposeResult:
        yield TopBar(self.path, "working…")
        with Vertical(classes="task"):
            yield Label(self.title_text, classes="dialog-title")
            yield Label(id="step")
            with Horizontal(id="bar-row"):
                yield Label(id="bar-label")
                yield ProgressBar(show_eta=False, id="file-bar")
                yield Label(id="bar-detail")
            # The whole job (meter.Meter): how far, how fast lately, when it'll be done.
            with Horizontal(id="all-row"):
                yield Label("All", id="all-label")
                yield ProgressBar(show_eta=False, show_percentage=True, id="all-bar")
            yield Label(id="all-detail")
            yield WrapLog(max_lines=2000, id="output")
            if touch.PHONE:
                yield KeyboardBox()
        yield KeyBar()

    def on_mount(self) -> None:
        media.SINK = self._progress
        logging.getLogger("telethon.client.users").addHandler(self._handler)
        self.app.begin_capture_print(self)
        self.set_interval(0.25, self._refresh_view)
        self.worker = self.run_worker(self._run(), exclusive=True, exit_on_error=False)

    def on_unmount(self) -> None:
        media.SINK = None
        logging.getLogger("telethon.client.users").removeHandler(self._handler)
        self.app.end_capture_print(self)

    def on_print(self, event: events.Print) -> None:
        for line in event.text.replace("\r", "\n").split("\n"):
            if line.strip():
                self.write(line)

    def write(self, text: str) -> None:
        self._pending.append(text)

    def _progress(self, label: str, done: int, total: int, note: str | None) -> None:
        self.bar = (label, done, total)
        if note:
            self.write(f"{label}: {note}")

    def _refresh_view(self) -> None:
        lines, self._pending = self._pending, []
        output = self.query_one("#output", WrapLog)
        for line in lines:
            output.write(Text(line))
        elapsed = int(time.monotonic() - self.started)
        stop = " - stopping after this file (Ctrl+C again: stop now)" if self.job.stopped else ""
        self.query_one("#step", Label).update(f"{self.step_text}{stop}")
        hours, rest = divmod(elapsed, 3600)
        took = f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"
        meter = media.METER
        left = meter.seconds_left() if meter is not None else None
        eta = f" · {duration(left)} left" if left else ""
        self.query_one(TopBar).set_info(f"working… {took}{eta}")
        self.query_one("#all-row").display = meter is not None
        self.query_one("#all-detail").display = meter is not None
        if meter is not None:
            self.query_one("#all-bar", ProgressBar).update(total=max(meter.total, 1), progress=meter.progress)
            files = f"{meter.units_done} of {meter.units} done · "
            self.query_one("#all-detail", Label).update(files + meter.summary().split(" · ", 1)[1])
        row = self.query_one("#bar-row")
        row.display = self.bar is not None
        if self.bar:
            label, done, total = self.bar
            self.query_one("#bar-label", Label).update(label)
            self.query_one("#file-bar", ProgressBar).update(total=max(total, 1), progress=done)
            self.query_one("#bar-detail", Label).update(f"{human(done)} / {human(total)}")

    async def _run(self) -> None:
        try:
            value = await self.work(self.job)
            self.dismiss(Outcome(True, value, stopped=self.job.stopped))
        except SystemExit as e:  # keepgram's "can't do that because ..." messages
            self.dismiss(Outcome(False, error=str(e.code), stopped=self.job.stopped))
        except Exception as e:
            self.dismiss(Outcome(False, error=f"{type(e).__name__}: {e}", stopped=self.job.stopped))

    def action_stop(self) -> None:
        if not self.job.stopped:
            self.job.stopped = True
            self.write("Stopping after the current file - press Ctrl+C again to stop right now.")
        elif self.worker is not None:
            self.worker.cancel()
            self.dismiss(Outcome(False, error="Stopped right away. Run it again to continue.", stopped=True))
