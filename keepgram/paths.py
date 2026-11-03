"""Where keepgram keeps things.

Run from the repo (./run.sh, run.bat) everything stays in the repo: config.json
beside README.md, the login and the records in data/. Installed with pip
somewhere else (a phone, say) it uses ~/keepgram instead. KEEPGRAM_HOME
overrides both."""

from __future__ import annotations

import os
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _home() -> Path:
    if os.environ.get("KEEPGRAM_HOME"):
        return Path(os.environ["KEEPGRAM_HOME"]).expanduser()
    if (_REPO / "pyproject.toml").is_file():
        return _REPO
    return Path.home() / "keepgram"


HOME = _home()
CONFIG = HOME / "config.json"
DATA = HOME / "data"
# A full login to the account - same weight as your phone with Telegram open.
SESSION = DATA / "keepgram.session"
STATE = DATA / "state.db"
# The watcher's own copy of the login (same account, its own file - so it and
# the menus never lock each other out), and what it did.
WATCH_SESSION = DATA / "watch.session"
WATCH_LOG = DATA / "watch.log"
TMP = DATA / "tmp"
# The bot's own login and records - separate from yours.
BOT_SESSION = DATA / "bot.session"
BOT_STATE = DATA / "bot.db"
# Drop-in plug-ins (see plugins/README.md).
PLUGINS = HOME / "plugins"
