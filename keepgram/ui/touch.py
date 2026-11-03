"""Phones: the on-screen keyboard comes back with a tap.

Termux (Android) shows its keyboard on a tap only while the program in it
isn't taking the mouse (TermuxTerminalViewClient.onSingleTapUp checks
isMouseTrackingActive). The menus take the mouse for their taps, so once the
keyboard had gone - the back key, a trip to the browser for the api_id or to
Telegram for the login code - no tap brought it back, and the menu login
stuck at a question there was no keyboard to answer (found 2026-11-03;
./run.sh login asks plain questions, no mouse, and worked).

So on a phone the menus let go of the mouse
- while a text box has the cursor: any tap then brings the keyboard;
- for a moment after a tap on a KeyboardBox (the log screen has one). Termux
  hands the tap to the program at once but decides about the keyboard only
  when it knows the tap wasn't half of a double tap, ~300 ms later - by then
  the mouse is free, so that same tap opens it. The mouse is taken back once
  the window changes size (the keyboard is up) or after a few seconds."""

from __future__ import annotations

import os
import time

PHONE = bool(os.environ.get("TERMUX_VERSION")) or "com.termux" in os.environ.get("PREFIX", "")
FREE_FOR = 3.0  # seconds the mouse stays free after a tap on a KeyboardBox


def keyboard_please(app) -> None:
    """A tap on a KeyboardBox: let go of the mouse right now."""
    app.keyboard_asked = (time.monotonic() + FREE_FOR, app.size)
    sync(app)
    app.set_timer(FREE_FOR + 0.1, lambda: sync(app))


def sync(app) -> None:
    """Take or free the mouse, whichever this moment wants. Cheap: on a phone
    the menus call it four times a second."""
    if not PHONE:
        return
    from keepgram.ui.widgets import TextInput

    try:
        typing = isinstance(app.focused, TextInput)
    except Exception:  # no screen yet, or closing
        return
    until, size = getattr(app, "keyboard_asked", (0.0, None))
    if until and (time.monotonic() >= until or app.size != size):
        until = 0.0  # the keyboard came up (the window got shorter), or time is up
        app.keyboard_asked = (0.0, None)
    free = typing or until > 0
    if free != getattr(app, "mouse_free", False):
        app.mouse_free = free
        # Textual's own switches (LinuxDriver); the test driver has none.
        switch = getattr(app._driver, "_disable_mouse_support" if free else "_enable_mouse_support", None)
        if switch is not None:
            switch()
