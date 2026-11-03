"""How far a long job is, how fast it's going, and when it'll be done.

A job is a list of units (a file to copy, a part to upload), each worth some
bytes. Progress callbacks report the unit in flight; the caller says when a
unit is over (done, failed or skipped - either way, it's no longer ahead).

The speed is measured over the last two minutes, not since the start, so the
estimate follows the connection as it gets faster or slower instead of being
dragged by the first minutes forever."""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timedelta

WINDOW = 120.0  # seconds of history the speed is taken from
SETTLE = 5.0  # no estimate before this much has been measured


class Meter:
    def __init__(self, total: int, units: int, clock=time.monotonic):
        self.total = max(0, int(total))
        self.units = units
        self.units_done = 0
        self.done = 0  # bytes of the units that are over
        self.partials: dict[str, int] = {}  # bytes so far of what's in flight, by progress label
        self.clock = clock
        self.started = clock()
        self.samples: deque[tuple[float, int]] = deque([(self.started, 0)])

    # -- reports ---------------------------------------------------------------

    def partial(self, label: str, done: int) -> None:
        self.partials[label] = done
        self._sample()

    def finish_unit(self, size: int) -> None:
        """A unit is over - done or failed - worth `size` bytes of the total."""
        self.done += size
        self.units_done += 1
        self.partials.clear()
        self._sample()

    def skip_unit(self, size: int) -> None:
        """A unit there turned out to be nothing to do for (already copied)."""
        self.total = max(0, self.total - size)
        self.units = max(0, self.units - 1)
        self.partials.clear()

    def _sample(self) -> None:
        now = self.clock()
        if now - self.samples[-1][0] < 1.0:
            return
        self.samples.append((now, self.progress))
        while len(self.samples) > 2 and now - self.samples[1][0] > WINDOW:
            self.samples.popleft()

    # -- answers ---------------------------------------------------------------

    @property
    def progress(self) -> int:
        return min(self.total, self.done + sum(self.partials.values()))

    @property
    def fraction(self) -> float:
        return self.progress / self.total if self.total else 1.0

    def speed(self) -> float | None:
        """Bytes per second lately; None until there's enough to tell."""
        now = self.clock()
        t0, p0 = self.samples[0]
        span = now - t0
        if span < SETTLE:
            return None
        moved = self.progress - p0
        return max(moved, 0) / span

    def seconds_left(self) -> float | None:
        speed = self.speed()
        left = self.total - self.progress
        if left <= 0:
            return 0.0
        if not speed:
            return None
        return left / speed

    def summary(self) -> str:
        from keepgram.media import human

        parts = [f"{self.fraction:.0%}", f"{human(self.progress)} of {human(self.total)}"]
        speed, left = self.speed(), self.seconds_left()
        if speed is None:
            parts.append("measuring the speed …")
        else:
            parts.append(f"{human(speed)}/s")
            if left is not None:
                parts.append(f"{duration(left)} left · done {finish_at(left)}")
            else:
                parts.append("stalled")
        return " · ".join(parts)


def duration(seconds: float) -> str:
    if seconds < 60:
        return "less than a minute"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"about {minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"about {hours} h {minutes} min" if minutes else f"about {hours} h"
    days, hours = divmod(hours, 24)
    day = f"about {days} day{'s' if days > 1 else ''}"
    return f"{day} {hours} h" if hours else day


def _clock(t: datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")  # 12-hour, like the PC's own clock


def finish_at(seconds: float, now: datetime | None = None) -> str:
    now = now or datetime.now()
    end = now + timedelta(seconds=seconds)
    if end.date() == now.date():
        return f"around {_clock(end)}"
    if end.date() == (now + timedelta(days=1)).date():
        return f"around {_clock(end)} tomorrow"
    return f"around {end.strftime('%a')} {_clock(end)}"
