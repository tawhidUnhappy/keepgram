"""Fast transfers: several 512 KB pieces in flight at once, and - for a copy -
each piece uploaded the moment it has been downloaded.

Measured on a home connection (2026-11-03): one piece at a time ran 2.5 MB/s
down and 1.5 MB/s up; several at once, about 5 MB/s down and 7.8 MB/s up. A
57 MB copy went from 118 s (download all, then upload all) to about 27 s, and
writes nothing to disk; a 114 MB folder upload from about 105 s to 19 s.

Telegram takes a file's pieces in any order (upload.saveBigFilePart has the
piece number), which is what lets download and upload overlap. Files of 10 MB
or less use upload.saveFilePart and need an MD5 of the whole file, so their
pieces are kept in memory until the end - at most 10 MB."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import random

from telethon import errors
from telethon.tl import functions, types

PART = 512 * 1024
BIG = 10 * 1024 * 1024  # over this, Telegram wants the big-file upload
# Pieces in flight, spread over LINES extra connections per direction.
# Measured 2026-11-03: Telegram caps uploads from accounts without Premium -
# FLOOD_PREMIUM_WAIT, "a wait of 14 seconds is required in non-premium
# accounts" after a burst of ~18 MB, about 1 MB/s sustained, whatever the
# connection. 2-4 lines at 16 down / 8 up did best (1.28 MB/s copied); more
# requests only earned more waits. So uploads back off when told (Gate), and
# with Premium (limits.py sees it) the cap is gone and they don't need to.
DOWN_AT_ONCE = 16
UP_AT_ONCE = 8
LINES = 2
TRIES = 4


class Gate:
    """How many uploads may be in flight - fewer when Telegram says slow down,
    more again after a stretch without complaint. Shared by a whole run, so one
    file's FLOOD_WAIT slows them all down instead of each finding out alone."""

    def __init__(self, most: int):
        self.most = most
        self.limit = most
        self.busy = 0
        self.calm = 0
        self.cond = asyncio.Condition()

    async def __aenter__(self):
        async with self.cond:
            await self.cond.wait_for(lambda: self.busy < self.limit)
            self.busy += 1

    async def __aexit__(self, *exc):
        async with self.cond:
            self.busy -= 1
            self.cond.notify_all()

    async def flood(self, seconds: int) -> None:
        """Told to wait: halve the uploads in flight, then wait as told."""
        async with self.cond:
            self.limit = max(1, self.limit // 2)
            self.calm = 0
        _note_slow_down(seconds)
        await asyncio.sleep(seconds)

    async def ok(self) -> None:
        async with self.cond:
            self.calm += 1
            if self.calm >= 20 and self.limit < self.most:  # a while without complaint: one more
                self.limit += 1
                self.calm = 0
                self.cond.notify_all()


_last_note = 0.0


def _note_slow_down(seconds: int) -> None:
    """One line a minute, not one per piece."""
    import logging
    import time

    global _last_note
    if time.monotonic() - _last_note > 60:
        _last_note = time.monotonic()
        logging.getLogger("telethon.client.users").warning(
            "Telegram's upload limit for accounts without Premium (about 1 MB/s): asked to wait %ds - "
            "keepgram slows down and carries on by itself", seconds)


_gates: dict[int, Gate] = {}


def gate(client) -> Gate:
    if id(client) not in _gates:
        _gates[id(client)] = Gate(UP_AT_ONCE)
    return _gates[id(client)]


# -- extra connections ----------------------------------------------------------


async def _open_line(client, dc_id: int):
    """One more connection to a data centre, on the same login. Telethon keeps
    one; this opens another the way it opens one to a foreign data centre."""
    from telethon.network import MTProtoSender
    from telethon.tl.alltlobjects import LAYER

    if dc_id != client.session.dc_id:
        return await client._create_exported_sender(dc_id)  # a new one each call
    dc = await client._get_dc(dc_id)
    sender = MTProtoSender(client.session.auth_key, loggers=client._log)
    await sender.connect(client._connection(dc.ip_address, dc.port, dc.id, loggers=client._log,
                                            proxy=client._proxy, local_addr=client._local_addr))
    client._init_request.query = functions.help.GetConfigRequest()
    await sender.send(functions.InvokeWithLayerRequest(LAYER, client._init_request))
    return sender


class Lines:
    """A few connections to one data centre, shared by every transfer of a run
    and handed out by piece number. Without them (a client that can't open
    more - the tests' fake one), everything goes over the client's own."""

    def __init__(self, client, dc_id: int, count: int):
        self.client, self.dc_id, self.count = client, dc_id, count
        self.senders: list = []

    async def open(self) -> Lines:
        for _ in range(self.count):
            try:
                self.senders.append(await _open_line(self.client, self.dc_id))
            except Exception:  # noqa: BLE001 - fewer lines (or none) still works
                break
        return self

    async def ask(self, request, slot: int, flood_ok: bool = True):
        """flood_ok=False: a FLOOD_WAIT / FLOOD_PREMIUM_WAIT is raised for the
        caller to handle (uploads slow down) instead of slept out inside
        Telethon - sent on the connection directly, because Telethon's _call
        checks the client-wide threshold whatever is passed to it."""
        if self.senders:
            sender = self.senders[slot % len(self.senders)]
            if sender.is_connected():
                if flood_ok:
                    return await self.client._call(sender, request)
                return await sender.send(request)
        return await self.client(request)

    async def close(self) -> None:
        for sender in self.senders:
            with contextlib.suppress(Exception):  # closing what's already closed
                await sender.disconnect()
        self.senders.clear()


_lines: dict[tuple[int, int, str], Lines] = {}
_lines_lock = asyncio.Lock()


async def lines(client, dc_id: int | None, purpose: str) -> Lines:
    """The run's lines to `dc_id` for `purpose` ("down" or "up"), opened on
    first use and kept until close(client)."""
    home = getattr(getattr(client, "session", None), "dc_id", None)
    dc_id = dc_id or home or 0
    key = (id(client), dc_id, purpose)
    async with _lines_lock:
        if key not in _lines:
            pool = Lines(client, dc_id, LINES)
            if home is not None:
                await pool.open()
            _lines[key] = pool
        return _lines[key]


async def close(client) -> None:
    """Close the extra connections a run opened."""
    for key in [k for k in _lines if k[0] == id(client)]:
        await _lines.pop(key).close()
    _gates.pop(id(client), None)


def part_count(size: int) -> int:
    return max(1, (size + PART - 1) // PART)


class _Uploader:
    """Pieces in, InputFile out - in any order, several at once."""

    def __init__(self, client, size: int, name: str, line_pool: Lines | None = None):
        self.client, self.size, self.name = client, size, name
        self.lines = line_pool
        self.gate = gate(client)
        self.parts = part_count(size)
        self.big = size > BIG
        self.file_id = random.getrandbits(63)
        self.small: dict[int, bytes] = {}

    async def put(self, index: int, data: bytes) -> None:
        if self.big:
            request = functions.upload.SaveBigFilePartRequest(self.file_id, index, self.parts, data)
        else:
            self.small[index] = data
            request = functions.upload.SaveFilePartRequest(self.file_id, index, data)
        while True:
            async with self.gate:
                try:
                    if self.lines is not None:
                        await _retry(lambda: self.lines.ask(request, index, flood_ok=False))
                    else:
                        await _retry(lambda: self.client(request))
                except (errors.FloodWaitError, errors.FloodPremiumWaitError) as e:
                    wait = max(1, e.seconds)
                else:
                    await self.gate.ok()
                    return
            await self.gate.flood(wait)  # outside the gate: the others carry on, fewer at a time

    def handle(self):
        if self.big:
            return types.InputFileBig(self.file_id, self.parts, self.name)
        md5 = hashlib.md5(b"".join(self.small[i] for i in range(self.parts))).hexdigest()
        return types.InputFile(self.file_id, self.parts, self.name, md5)


async def _retry(call, tries: int = TRIES):
    """A piece that fails for a passing reason (connection hiccup, Telegram's
    own 5xx) is tried again; anything else is a real failure."""
    for attempt in range(tries):
        try:
            return await call()
        except (ConnectionError, TimeoutError, asyncio.TimeoutError, errors.ServerError, errors.RpcCallFailError):
            if attempt == tries - 1:
                raise
            await asyncio.sleep(1 + attempt * 2)


async def _run_all(tasks) -> None:
    """Run tasks together; if one fails, stop the rest and raise its error."""
    tasks = [asyncio.ensure_future(t) for t in tasks]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def upload(client, file, size: int, name: str, progress=None, at_once: int = UP_AT_ONCE):
    """Upload a path or a readable stream (a FileSlice) of `size` bytes; returns
    the InputFile / InputFileBig to send. Pieces are read in order (the disk
    likes that) and sent several at a time."""
    up = _Uploader(client, size, name, await lines(client, None, "up"))
    stream = open(file, "rb") if isinstance(file, (str, os.PathLike)) else file  # noqa: SIM115
    queue: asyncio.Queue = asyncio.Queue(maxsize=at_once * 2)
    sent = 0

    async def reader():
        for index in range(up.parts):
            data = stream.read(PART)
            if index < up.parts - 1 and len(data) != PART:
                raise OSError(f"{name}: the file got shorter while it was being read")
            await queue.put((index, data))
        for _ in range(at_once):
            await queue.put(None)

    async def sender():
        nonlocal sent
        while (item := await queue.get()) is not None:
            await up.put(*item)
            sent += len(item[1])
            if progress:
                progress(sent, size)

    try:
        await _run_all([reader(), *(sender() for _ in range(at_once))])
    finally:
        if stream is not file:
            stream.close()
    return up.handle()


class _Downloader:
    """Pieces of a document, by number, from whichever data centre holds it."""

    def __init__(self, client, msg):
        self.client, self.msg = client, msg
        self.doc = msg.media.document
        self.sender = None
        self.lines: Lines | None = None
        self._refresh = asyncio.Lock()

    def _location(self):
        d = self.doc
        return types.InputDocumentFileLocation(d.id, d.access_hash, d.file_reference, "")

    async def __aenter__(self):
        self.lines = await lines(self.client, self.doc.dc_id, "down")
        home = getattr(getattr(self.client, "session", None), "dc_id", None)
        if (not self.lines.senders and home is not None and self.doc.dc_id != home
                and hasattr(self.client, "_borrow_exported_sender")):
            self.sender = await self.client._borrow_exported_sender(self.doc.dc_id)
        return self

    async def __aexit__(self, *exc):
        if self.sender is not None:
            await self.client._return_exported_sender(self.sender)

    async def _ask(self, request, slot: int = 0):
        if self.lines is not None and self.lines.senders:
            return await self.lines.ask(request, slot)
        if self.sender is not None:
            return await self.client._call(self.sender, request)
        return await self.client(request)

    async def get(self, index: int) -> bytes:
        for attempt in range(2):
            try:
                result = await _retry(lambda: self._ask(
                    functions.upload.GetFileRequest(self._location(), index * PART, PART), index))
                return result.bytes
            except errors.FileReferenceExpiredError:
                if attempt:
                    raise
                async with self._refresh:  # the file's access ran out: ask for the message again
                    fresh = await self.client.get_messages(self.msg.peer_id, ids=self.msg.id)
                    if fresh is None or not isinstance(fresh.media, types.MessageMediaDocument):
                        raise
                    self.doc = fresh.media.document
        raise RuntimeError("unreachable")


async def copy_document(client, msg, name: str, progress=None, disk_path: str | None = None,
                        down_at_once: int = DOWN_AT_ONCE, up_at_once: int = UP_AT_ONCE):
    """Download a document and upload it again as a new file, piece by piece,
    the two at the same time. Returns the uploaded file's InputFile. With
    disk_path, the file is also written there (secure.local_copy_dir).
    progress(done, total) counts both halves: total is twice the size."""
    size = msg.media.document.size
    up = _Uploader(client, size, name, await lines(client, None, "up"))
    queue: asyncio.Queue = asyncio.Queue(maxsize=up_at_once * 4)
    next_index = 0
    moved = 0
    fd = os.open(disk_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644) if disk_path else None

    def tick(n: int) -> None:
        nonlocal moved
        moved += n
        if progress:
            progress(moved, 2 * size)

    async with _Downloader(client, msg) as down:

        async def fetcher():
            nonlocal next_index
            while next_index < up.parts:
                index = next_index
                next_index += 1
                data = await down.get(index)
                expected = min(PART, size - index * PART)
                if len(data) != expected:
                    raise OSError(f"{name}: piece {index} came back with {len(data)} bytes, not {expected}")
                if fd is not None:
                    os.pwrite(fd, data, index * PART)
                tick(len(data))
                await queue.put((index, data))

        async def sender():
            while (item := await queue.get()) is not None:
                await up.put(*item)
                tick(len(item[1]))

        async def fetch_all():
            await _run_all([fetcher() for _ in range(down_at_once)])
            for _ in range(up_at_once):
                await queue.put(None)

        try:
            await _run_all([fetch_all(), *(sender() for _ in range(up_at_once))])
        finally:
            if fd is not None:
                os.close(fd)
    return up.handle()
