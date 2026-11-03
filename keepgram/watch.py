"""watch: keepgram keeps working while you use Telegram - in a terminal window.
Close the window (or Ctrl+C) and it stops; nothing keeps running out of sight.

    folders    a chat you create (or leave) is put in (or taken out of) the
               Keepgram folders within seconds - a new folder when one is full
    keep_new   a file forwarded into one of your chats is copied as your own
               moments after it is posted

Only what is posted after the watcher first started is copied: a chat's
backlog is the "Make every file my own" job, which you start yourself - the
watcher never starts a big job on its own.

How it stays right: Telegram's updates say "something changed in chat X"
and the watcher then reads chat X from where it last stopped (watch_marks in
state.db) - so a missed update, a restart or a night offline loses nothing;
every few minutes it looks through every chat that way anyway. A failed copy
keeps the mark before it, so it is tried again. Copies in progress are claimed
in state.db, so the watcher and the menus never copy the same file twice."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from logging.handlers import RotatingFileHandler

from telethon import errors, events, utils
from telethon.tl import functions, types

from keepgram import chats, config, folders, limits, media, paths, plugins, secure, telegram
from keepgram.state import State

log = logging.getLogger("keepgram.watch")
SETTLE = 3.0  # seconds after an update before reading the chat: albums arrive in pieces
POLL = 60  # seconds between the quick checks of every chat


class Watcher:
    def __init__(self, client, cfg: dict, state: State):
        self.client, self.cfg, self.state = client, cfg, state
        self.owned: dict[int, chats.OwnedChat] = {}
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self.waiting: set[int] = set()
        self.poked_at: dict[int, float] = {}
        self.kept_total = 0  # copies made since this window started, for the "still watching" line
        self.folders_due = asyncio.Event()
        self.since = 0.0
        self.stopping = False
        self.me_id = 0

    # -- the chats you own, and their folders ---------------------------------

    async def refresh_chats(self) -> None:
        owned = await chats.owned_chats(self.client, self.cfg["include_admin_chats"])
        self.owned = {c.id: c for c in owned}
        for chat in owned:
            if self.state.mark(chat.id) is None:
                await self._first_mark(chat)

    async def _first_mark(self, chat) -> None:
        """Where watching a chat starts: its newest message - or its very start,
        for a chat made after the watcher first started (nothing old in it)."""
        made = getattr(chat.entity, "date", None)
        if made is not None and made.timestamp() > self.since:
            self.state.set_mark(chat.id, 0)
            return
        newest = await self.client.get_messages(chat.entity, limit=1)
        self.state.set_mark(chat.id, newest[0].id if newest else 0)

    async def sync_folders(self) -> None:
        if not self.cfg["watch"].get("folders", True):
            return
        plugins.load()
        owned = list(self.owned.values())
        sorter = plugins.get("sorter", self.cfg["folders"]["sorter"])
        groups = sorter.sort(sorted(owned, key=lambda c: c.title.casefold()), self.cfg["folders"]["name"])
        existing, raw, taken = await folders.read_existing(self.client)
        plans = folders.plan({k: [c.id for c in v] for k, v in groups.items()}, existing,
                             config.folder_size(self.cfg), taken)
        if all(p.action == "keep" for p in plans):
            return
        problems = await folders.apply(self.client, plans, {c.id: c.input_peer for c in owned}, raw,
                                       limits.folders(self.cfg))
        for p in plans:
            if p.action != "keep":
                log.info("folder %s: %s (+%d -%d)", p.title, p.action, len(p.added), len(p.removed))
        for problem in problems:
            log.warning("folders: %s", problem)

    # -- new files ------------------------------------------------------------

    def poke(self, chat_id: int, settle: bool = True) -> None:
        """Read this chat soon. settle: it just changed - give an album a moment
        to arrive whole first (a sweep's chats needn't wait)."""
        if settle:
            self.poked_at[chat_id] = time.monotonic()
        if chat_id in self.owned and chat_id not in self.waiting:
            self.waiting.add(chat_id)
            self.queue.put_nowait(chat_id)

    async def check_chat(self, chat) -> None:
        """Everything in the chat after its mark: copy what depends on others,
        then move the mark up to the newest message read - but never past a
        copy that failed, so it is tried again."""
        if not self.cfg["watch"].get("keep_new", True):
            return
        start = self.state.mark(chat.id) or 0
        newest = start

        async def after_mark(_chat):
            nonlocal newest
            async for msg in self.client.iter_messages(chat.entity, min_id=start, reverse=True):
                newest = max(newest, msg.id)
                yield msg

        result = await secure.scan(self.client, [chat], set(self.owned), self.cfg, self.state,
                                   messages=after_mark, progress=lambda r: None)
        for note in result.notes:
            log.info("%s", note)
        failed_at = None
        if result.jobs:
            for job in result.jobs:
                log.info("%s #%d: copying %d file(s) from %s", chat.title, job.own[0].id, len(job.dep.files),
                         job.dep.source)
            done, problems = await secure.run(self.client, result.jobs, self.cfg, self.state,
                                              report=lambda *a: None, cancelled=lambda: self.stopping)
            for problem in problems:
                log.warning("%s", problem)
            left = [m.id for j in result.jobs for m in j.own if not self.state.is_kept(chat.id, m.id)]
            if left:
                failed_at = min(left)
            self.kept_total += done
            log.info("%s: kept %d of %d", chat.title, done, len(result.jobs))
        self.state.set_mark(chat.id, min(newest, failed_at - 1) if failed_at else newest)

    # -- running ----------------------------------------------------------------

    async def _worker(self) -> None:
        while not self.stopping:
            chat_id = await self.queue.get()
            wait = SETTLE - (time.monotonic() - self.poked_at.pop(chat_id, -SETTLE))
            if wait > 0:
                await asyncio.sleep(wait)
            self.waiting.discard(chat_id)
            chat = self.owned.get(chat_id)
            if chat is None:
                continue
            try:
                await self.check_chat(chat)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # never let one chat stop the watcher; its mark makes it retry
                log.warning("%s: %s: %s - tried again later", chat.title, type(e).__name__, e)

    async def _folders_loop(self) -> None:
        last = 0.0
        while not self.stopping:
            await self.folders_due.wait()
            # one sync for a burst of changes, and at most one a minute
            await asyncio.sleep(max(10.0, 60.0 - (time.monotonic() - last)))
            self.folders_due.clear()
            last = time.monotonic()
            try:
                await self.refresh_chats()
                await self.sync_folders()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("folders: %s: %s - tried again later", type(e).__name__, e)

    async def _poll_loop(self) -> None:
        """Once a minute, one request: the newest message of every chat of yours.
        A chat whose newest is past its mark gets read. This is what catches
        what Telegram never announces to this connection - your own other
        keepgram (same login) making a channel or posting, say."""
        while not self.stopping:
            await asyncio.sleep(POLL)
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("check: %s: %s - tried again in a minute", type(e).__name__, e)

    async def _poll_once(self) -> None:
        # a chat made just now shows among the most recent ones
        async for dialog in self.client.iter_dialogs(limit=20):
            if chats._owned(dialog.entity, self.cfg["include_admin_chats"]) and dialog.id not in self.owned:
                self.folders_due.set()
        ids = list(self.owned)
        for i in range(0, len(ids), 50):
            batch = [self.owned[c] for c in ids[i:i + 50]]
            try:
                result = await self.client(functions.messages.GetPeerDialogsRequest(
                    peers=[types.InputDialogPeer(c.input_peer) for c in batch]))
            except errors.RPCError:
                self.folders_due.set()  # one of them is gone: the folder loop takes it out
                continue
            for dialog in result.dialogs:
                chat_id = utils.get_peer_id(dialog.peer)
                if dialog.top_message > (self.state.mark(chat_id) or 0):
                    self.poke(chat_id)

    async def _sweep_loop(self) -> None:
        minutes = max(1, int(self.cfg["watch"].get("every_minutes") or 10))
        while not self.stopping:
            await asyncio.sleep(minutes * 60)
            self.folders_due.set()
            for chat_id in list(self.owned):
                self.poke(chat_id, settle=False)
            # A quiet window looks the same as a stuck one - so say it's alive.
            log.info("still watching %d chats - %d file(s) kept since this window started",
                     len(self.owned), self.kept_total)

    def _wire(self) -> None:
        c = self.client

        @c.on(events.NewMessage())
        async def new_message(event):
            self.poke(event.chat_id)

        @c.on(events.ChatAction())
        async def chat_action(event):
            # A chat made or renamed, or you joining / leaving one, may change the
            # folders; other people coming and going in big groups doesn't.
            if (event.created or (event.new_title and event.chat_id in self.owned)
                    or self.me_id in (event.user_ids or [event.user_id])):
                self.folders_due.set()

        @c.on(events.Raw(types.UpdateChannel))
        async def channel_changed(update):
            # Sent when you join, leave or delete a channel - and for many small
            # changes too; the folder loop sorts it out at most once a minute.
            self.folders_due.set()

    async def run(self) -> None:
        self.me_id = (await self.client.get_me()).id
        since = self.state.get_meta("watch_since")
        if since is None:
            since = str(time.time())
            self.state.set_meta("watch_since", since)
        self.since = float(since)
        await self.refresh_chats()
        await self.sync_folders()
        log.info("watching %d chats - leave this window open; close it or press Ctrl+C to stop", len(self.owned))
        self._wire()
        for chat_id in self.owned:  # whatever came while it wasn't running
            self.poke(chat_id, settle=False)
        tasks = [asyncio.create_task(self._worker()), asyncio.create_task(self._folders_loop()),
                 asyncio.create_task(self._poll_loop()), asyncio.create_task(self._sweep_loop())]
        try:
            await self.client.disconnected
            log.warning("lost the connection to Telegram")
        finally:
            self.stopping = True
            for t in tasks:
                t.cancel()


class AlreadyWatching(SystemExit):
    pass


def hold_lock():
    """Only one watcher at a time. The lock is the operating system's, on
    data/watch.lock: it goes the moment the process ends - however it ends,
    window closed included - so there is nothing to clean up. Returns the open
    file; keep it for as long as the watcher runs."""
    paths.DATA.mkdir(parents=True, exist_ok=True)
    f = open(paths.DATA / "watch.lock", "a+")  # noqa: SIM115 - held open on purpose
    try:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise AlreadyWatching("keepgram is already watching in another window - use that one, "
                              "or close it first") from None
    return f


def watching_elsewhere() -> bool:
    try:
        hold_lock().close()
        return False
    except AlreadyWatching:
        return True


def recent(lines: int = 40) -> str:
    if not paths.WATCH_LOG.is_file():
        return "Nothing yet."
    return "\n".join(paths.WATCH_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def setup_log(to_console: bool = True) -> None:
    paths.DATA.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %I:%M:%S %p")
    if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        handler = RotatingFileHandler(paths.WATCH_LOG, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(fmt)
        log.addHandler(handler)
    if to_console and not any(type(h) is logging.StreamHandler for h in log.handlers):
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        log.addHandler(console)


async def connect(cfg: dict):
    client = telegram.make_client(cfg, telegram.watch_session())
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise SystemExit("keepgram's login is gone (logged out?) - log in again, then start watching again")
    await telegram.listen(client)
    await limits.learn(client, cfg)
    return client


RECONNECT = 30  # seconds to wait before connecting again


async def watch(cfg: dict, to_console: bool = True) -> None:
    """Watch until the window is closed or Ctrl+C. A lost connection (Wi-Fi
    gone, PC asleep) is waited out and connected again, in the same window."""
    lock = hold_lock()
    setup_log(to_console)
    media.QUIET = True
    state = State()
    try:
        while True:
            try:
                client = await connect(cfg)
            except (OSError, ConnectionError) as e:
                log.warning("can't reach Telegram (%s) - trying again in %d seconds", e, RECONNECT)
                await asyncio.sleep(RECONNECT)
                continue
            try:
                me = await client.get_me()
                log.info("keepgram is watching as %s", utils.get_display_name(me))
                await Watcher(client, cfg, state).run()
            except errors.AuthKeyUnregisteredError:
                raise SystemExit("keepgram's login was ended (Settings → Devices, or log out) - log in again") from None
            except (OSError, ConnectionError) as e:
                log.warning("connection trouble: %s", e)
            finally:
                await client.disconnect()
            log.warning("lost the connection to Telegram - connecting again in %d seconds", RECONNECT)
            await asyncio.sleep(RECONNECT)
    finally:
        state.close()
        lock.close()
