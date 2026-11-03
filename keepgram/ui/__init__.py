"""keepgram's menus: ./run.sh with no command."""

from __future__ import annotations

import sys


def run() -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("The menus need an interactive terminal. Use the commands instead - see ./run.sh --help")
        return
    from keepgram.ui.app import KeepgramApp

    KeepgramApp().run()
