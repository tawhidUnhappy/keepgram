"""verify: proves that a folder sent with `upload` is in the chat, byte for byte.

For every file of the folder - every part, for a file sent in parts - the
message holding it is looked for: first the one keepgram recorded when it sent
it, then any file in the chat with the same name and size. Its document is
downloaded again, piece by piece, straight into SHA-256 (nothing is written to
disk), and compared with the SHA-256 of the same bytes on disk, read fresh. A
file counts as there only when the two are equal.

Nothing is changed unless asked: with fix, whatever is missing or different is
sent again (and checked the same way), and a copy that turned out different is
deleted once its replacement is proved."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from telethon.tl import types

from keepgram import config, transfer, upload
from keepgram.media import Progress, file_name, has_file
from keepgram.state import State

MB = config.MB
WINDOW = 4  # pieces in flight per downloader, times DOWN_AT_ONCE, at most - bounds the memory used
# The start of the last line when everything checks out - other programs look for it.
ALL_IDENTICAL = "All identical:"


@dataclass
class Check:
    item: upload.Item
    piece: upload.Piece
    sha256: str = ""  # of these bytes on disk
    msg_id: int | None = None  # the message proved to hold them
    bad: list[int] = field(default_factory=list)  # messages with this name and size but other bytes

    @property
    def ok(self) -> bool:
        return self.msg_id is not None


def local_sha256(item: upload.Item, piece: upload.Piece) -> str:
    """The SHA-256 of a piece's bytes, read from the disk now."""
    digest = hashlib.sha256()
    with Path(item.path).open("rb") as f:
        f.seek(piece.offset)
        left = piece.length
        while left:
            chunk = f.read(min(4 * MB, left))
            if not chunk:
                raise OSError(f"{item.rel} is shorter than {piece.offset + piece.length} bytes now")
            digest.update(chunk)
            left -= len(chunk)
    return digest.hexdigest()


async def remote_sha256(client, msg, progress=None, at_once: int = transfer.DOWN_AT_ONCE) -> str:
    """The SHA-256 of a document as Telegram has it: its pieces downloaded
    several at a time and hashed in order."""
    size = msg.media.document.size
    parts = transfer.part_count(size)
    digest = hashlib.sha256()
    got: dict[int, bytes] = {}
    state = {"next": 0, "hashed": 0, "done": 0}
    turn = asyncio.Condition()
    window = at_once * WINDOW

    async with transfer._Downloader(client, msg) as down:

        async def fetcher():
            while True:
                async with turn:
                    await turn.wait_for(lambda: state["next"] >= parts or state["next"] - state["hashed"] < window)
                    if state["next"] >= parts:
                        return
                    index = state["next"]
                    state["next"] += 1
                data = await down.get(index)
                expected = min(transfer.PART, size - index * transfer.PART) if size else 0
                if len(data) != expected:
                    raise OSError(f"piece {index} came back with {len(data)} bytes, not {expected}")
                async with turn:
                    got[index] = data
                    while state["hashed"] in got:
                        chunk = got.pop(state["hashed"])
                        digest.update(chunk)
                        state["done"] += len(chunk)
                        state["hashed"] += 1
                    turn.notify_all()
                if progress:
                    progress(state["done"], size)

        await transfer._run_all([fetcher() for _ in range(min(at_once, parts))])
    return digest.hexdigest()


async def documents(client, entity) -> dict[tuple[str, int], list]:
    """Every file in the chat, by (name, size), newest first."""
    found: dict[tuple[str, int], list] = {}
    async for msg in client.iter_messages(entity, filter=types.InputMessagesFilterDocument):
        if has_file(msg) and isinstance(msg.media, types.MessageMediaDocument):
            found.setdefault((file_name(msg), msg.media.document.size), []).append(msg)
    return found


def plan_checks(plan: upload.Plan, cfg: dict, state: State) -> list[Check]:
    """Each file's pieces, cut the way upload cuts them, with their SHA-256
    read fresh from the disk (keepgram's hash cache is not trusted here)."""
    size = upload.part_size(cfg)
    checks = []
    for item in plan.items:
        prog = Progress(f"reading {item.rel}") if item.size > 256 * MB else None
        item.sha256 = local_sha256(item, upload.Piece(item.rel, 0, item.size, 1, 1))
        if prog:
            prog.end("read")
        state.store_hash(item.path, item.size, item.mtime_ns, item.sha256)
        item.pieces = upload.cut(Path(item.rel).name, item.size, size)
        for piece in item.pieces:
            sha = item.sha256 if piece.parts == 1 else local_sha256(item, piece)
            checks.append(Check(item, piece, sha))
    return checks


async def _candidates(client, entity, chat_id: int, check: Check, state: State, in_chat: dict) -> list:
    recorded = state.uploaded_msg(chat_id, check.item.sha256, check.piece.part, check.piece.parts)
    found = []
    if recorded is not None:
        msg = await client.get_messages(entity, ids=recorded)
        if msg is not None and has_file(msg) and isinstance(msg.media, types.MessageMediaDocument):
            found.append(msg)
    seen = {m.id for m in found}
    found += [m for m in in_chat.get((check.piece.name, check.piece.length), []) if m.id not in seen]
    return [m for m in found if m.media.document.size == check.piece.length]


async def check_all(client, entity, chat_id: int, checks: list[Check], state: State) -> None:
    """Fills in each check: the message proved to hold its bytes, or the
    messages that have its name and size but other bytes."""
    in_chat = await documents(client, entity)
    for n, check in enumerate(checks, 1):
        label = check.piece.name if check.piece.parts > 1 else check.item.rel
        for msg in await _candidates(client, entity, chat_id, check, state, in_chat):
            prog = Progress(f"[{n}/{len(checks)}] reading back {label}")
            got = await remote_sha256(client, msg, prog)
            if got == check.sha256:
                prog.end("identical")
                check.msg_id = msg.id
                state.mark_uploaded(chat_id, check.item.sha256, check.piece.part, check.piece.parts,
                                    check.item.rel, check.item.size, msg.id)
                break
            prog.end("DIFFERENT")
            check.bad.append(msg.id)
        if not check.ok and not check.bad:
            print(f"  [{n}/{len(checks)}] {label}: missing")


async def fix(client, entity, chat_id: int, plan: upload.Plan, checks: list[Check], cfg: dict, state: State) -> None:
    """Sends again what is missing or different, proves each new copy, then
    deletes the copies that were different."""
    todo = [c for c in checks if not c.ok]
    if not todo:
        return
    skip = {(c.item.rel, c.piece.part) for c in checks if c.ok}
    resend = upload.Plan([i for i in plan.items if any(c.item is i for c in todo)], [])
    print(f"Sending {len(todo)} file(s)/part(s) again ...")
    await upload.send(client, entity, chat_id, resend, skip, cfg, state)
    again = [Check(c.item, c.piece, c.sha256) for c in todo]
    await check_all(client, entity, chat_id, again, state)
    for old, new in zip(todo, again, strict=True):
        new.bad = [m for m in new.bad if m not in old.bad]
        if new.ok and old.bad:
            await client.delete_messages(entity, old.bad)
            print(f"  deleted the different copy of {old.piece.name} (message {', '.join(map(str, old.bad))})")
        old.msg_id, old.bad = new.msg_id, (new.bad if not new.ok else [])
