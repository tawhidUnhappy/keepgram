"""The Telegram connection: your own account through your own API app, with
Telegram's "slow down" waits honoured rather than failing."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from telethon import TelegramClient

from keepgram import __version__, paths

# Telegram tells a client to wait when it goes too fast (FLOOD_WAIT). Waits up
# to a day are slept through; long jobs then just take longer instead of dying.
FLOOD_SLEEP = 24 * 3600


def _show_flood_waits() -> None:
    # A no-op when the menus already put their own handler on the root logger.
    logging.basicConfig(level=logging.WARNING, format="  [telegram] %(message)s")
    # Telethon says "Sleeping for 37s (0:00:37) on SendMediaRequest flood wait" here.
    logging.getLogger("telethon.client.users").setLevel(logging.INFO)


def make_client(cfg: dict, session=None) -> TelegramClient:
    if not cfg.get("api_id") or not cfg.get("api_hash"):
        raise SystemExit("No api_id / api_hash yet - run: login")
    paths.DATA.mkdir(parents=True, exist_ok=True)
    _show_flood_waits()
    if session is None and _logged_in_file():
        # Every keepgram works on its own copy of the login. Telethon keeps its
        # session file write-locked between saves, so two programs on one file
        # sooner or later stop each other with "database is locked" - found
        # 2026-11-03, a test run beside the user's menus. data/keepgram.session
        # itself is only used to log in.
        session = session_copy(paths.DATA / "sessions" / f"{os.getpid()}.session")
    return TelegramClient(
        str(session or paths.SESSION),
        int(cfg["api_id"]),
        cfg["api_hash"],
        flood_sleep_threshold=FLOOD_SLEEP,
        device_model="keepgram",
        app_version=__version__,
    )


async def login(cfg: dict) -> TelegramClient:
    """Phone number, the code Telegram sends to your app, and your cloud
    password if you set one - asked in the terminal, once. Into the login file
    itself, which every keepgram then copies."""
    client = make_client(cfg, paths.SESSION)
    await client.start()
    _lock_session()
    from keepgram import limits

    await limits.learn(client, cfg)
    return client


async def connect(cfg: dict) -> TelegramClient:
    client = make_client(cfg)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise SystemExit("Not logged in - run: login")
    _lock_session()
    from keepgram import limits

    await limits.learn(client, cfg)
    return client


async def listen(client) -> None:
    """Ask Telegram to start sending live updates to this connection. A
    connection that never asks gets none - found on the first real run: the
    watcher sat there hearing nothing until it did this."""
    from telethon.tl import functions

    await client(functions.updates.GetStateRequest())


def _logged_in_file() -> bool:
    """Does data/keepgram.session hold a login (an auth key)? Read without
    taking a write lock."""
    import sqlite3

    if not paths.SESSION.is_file():
        return False
    try:
        con = sqlite3.connect(f"file:{paths.SESSION}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("SELECT auth_key FROM sessions").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return bool(row and row[0])


def session_copy(dest) -> str:
    """The same login as yours, copied into a file of its own. Two programs on
    one session file lock each other out (sqlite) and trip over each other's
    update state; on two files they don't. Copies left by keepgrams that have
    ended are removed on the way."""
    from telethon.sessions import SQLiteSession

    if not paths.SESSION.is_file():
        raise SystemExit("Not logged in - run: login")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _clear_old_copies(dest.parent)
    main = SQLiteSession(str(paths.SESSION))
    try:
        if main.auth_key is None:
            raise SystemExit("Not logged in - run: login")
        copy = SQLiteSession(str(dest))
        if copy.auth_key is None or copy.auth_key.key != main.auth_key.key:
            copy.set_dc(main.dc_id, main.server_address, main.port)
            copy.auth_key = main.auth_key
            copy.save()
        copy.close()
    finally:
        main.close()
    os.chmod(dest, 0o600)
    return str(dest)


def _clear_old_copies(folder) -> None:
    from keepgram.state import _alive

    if folder == paths.DATA:
        return  # watch.session lives here and is kept
    for f in Path(folder).glob("*.session*"):
        pid = f.name.split(".")[0]
        if pid.isdigit() and int(pid) != os.getpid() and not _alive(int(pid)):
            f.unlink(missing_ok=True)


def watch_session() -> str:
    """The watcher's login: a copy of yours in a file of its own (session_copy)."""
    return session_copy(paths.WATCH_SESSION)


def _lock_session() -> None:
    session = paths.SESSION
    if session.is_file():
        os.chmod(session, 0o600)
