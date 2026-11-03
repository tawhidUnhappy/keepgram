"""upload: a folder from disk into a Telegram chat - every file in it and in
its sub-folders, in name order, each with its path in the caption.

Files bigger than Telegram allows (2000 MB, 4000 MB with Premium) go up in
parts: name.ext.001, name.ext.002, ... read straight from the original file,
no copies on disk. The parts join back into the file with `join`, 7-Zip
("Combine files"), or `cat name.ext.0* > name.ext`.

Uploading the same folder again: the files already in that chat are found two
ways - keepgram's own record (by content, so a renamed or moved file still
counts) and the chat itself (same file name and size, so files uploaded from
another computer count too). You choose: skip them, or upload them again.
An upload that stopped half way continues where it was."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from telethon.tl import functions, types

from keepgram import config, media, thumbs
from keepgram.media import FileSlice, Progress, clip, has_file, input_media_file
from keepgram.meter import Meter
from keepgram.state import State

MB = config.MB


@dataclass
class Piece:
    name: str  # the file name it gets on Telegram
    offset: int
    length: int
    part: int  # 1-based
    parts: int


@dataclass
class Item:
    path: str
    rel: str  # path inside the folder, always with "/"
    size: int
    mtime_ns: int
    sha256: str = ""
    pieces: list[Piece] = field(default_factory=list)


@dataclass
class Plan:
    items: list[Item]
    skipped: list[str]

    @property
    def size(self) -> int:
        return sum(i.size for i in self.items)

    @property
    def split(self) -> list[Item]:
        return [i for i in self.items if len(i.pieces) > 1]


def walk(root: Path, skip_hidden: bool) -> Plan:
    items, skipped = [], []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if skip_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        dirnames.sort(key=str.casefold)
        for name in sorted(filenames, key=str.casefold):
            path = os.path.join(dirpath, name)
            rel = Path(path).relative_to(root).as_posix()
            if skip_hidden and name.startswith("."):
                continue
            if os.path.islink(path) or not os.path.isfile(path):
                skipped.append(f"{rel}: not a regular file")
                continue
            st = os.stat(path)
            if st.st_size == 0:
                skipped.append(f"{rel}: empty - Telegram can't store a 0-byte file")
                continue
            items.append(Item(path, rel, st.st_size, st.st_mtime_ns))
    return Plan(items, skipped)


def cut(name: str, size: int, part_size: int) -> list[Piece]:
    if size <= part_size:
        return [Piece(name, 0, size, 1, 1)]
    parts = (size + part_size - 1) // part_size
    width = max(3, len(str(parts)))
    return [
        Piece(f"{name}.{k + 1:0{width}d}", k * part_size, min(part_size, size - k * part_size), k + 1, parts)
        for k in range(parts)
    ]


def part_size(cfg: dict) -> int:
    limit = config.file_limit(cfg)
    wanted = int(cfg["upload"].get("part_mb") or 0) * MB
    return min(wanted, limit) if wanted > 0 else limit


def sha256_of(item: Item, state: State) -> str:
    cached = state.cached_hash(item.path, item.size, item.mtime_ns)
    if cached:
        return cached
    h = hashlib.sha256()
    prog = Progress(f"checking {item.rel}") if item.size > 256 * MB else None
    done = 0
    with open(item.path, "rb") as f:
        while chunk := f.read(4 * MB):
            h.update(chunk)
            done += len(chunk)
            if prog:
                prog(done, item.size)
    if prog:
        prog.end("checked")
    digest = h.hexdigest()
    state.store_hash(item.path, item.size, item.mtime_ns, digest)
    return digest


def caption(item: Item, piece: Piece) -> str:
    if piece.parts == 1:
        return clip(item.rel)
    lines = [
        item.rel,
        f"part {piece.part} of {piece.parts} - join all parts to open it "
        f"(keepgram join, 7-Zip \"Combine files\", or cat)",
        f"sha256 of the whole file: {item.sha256}",
    ]
    return clip("\n".join(lines))


async def files_in_chat(client, entity) -> set[tuple[str, int]]:
    """(file name, size) of every file already in the chat."""
    seen = set()
    async for msg in client.iter_messages(entity, filter=types.InputMessagesFilterDocument):
        if not has_file(msg) or not isinstance(msg.media, types.MessageMediaDocument):
            continue
        doc = msg.media.document
        name = next((a.file_name for a in doc.attributes if isinstance(a, types.DocumentAttributeFilename)), None)
        if name:
            seen.add((name, doc.size))
    return seen


async def resolve_target(client, to: str, owned: list):
    """me / saved, @username, a t.me link, a chat id, or the title of one of your chats."""
    from keepgram import chats

    if to.lower() in ("me", "saved", "self"):
        return await client.get_entity("me")
    if to.startswith("@") or "t.me/" in to or to.lstrip("-").isdigit():
        return await client.get_entity(int(to) if to.lstrip("-").isdigit() else to)
    found = chats.pick(owned, to)
    if len(found) != 1:
        names = ", ".join(c.title for c in found) or "none"
        raise SystemExit(f"{to!r} matches {len(found)} of your chats ({names}) - use its id from: chats")
    return found[0].entity


async def create_channel(client, title: str):
    """A new private channel for the folder - yours, so `folders` sorts it in."""
    result = await client(
        functions.channels.CreateChannelRequest(title=title[:128] or "Upload", about="Uploaded with keepgram",
                                                broadcast=True)
    )
    return result.chats[0]


@dataclass
class Duplicates:
    pieces: set[tuple[str, int]]  # (rel, part) already in the chat
    how: dict[str, str]  # rel -> why it counts as there


def find_duplicates(plan: Plan, chat_id: int, state: State, in_chat: set[tuple[str, int]]) -> Duplicates:
    out = Duplicates(set(), {})
    first_of: dict[str, str] = {}
    for item in plan.items:
        for p in item.pieces:
            if state.uploaded_msg(chat_id, item.sha256, p.part, p.parts) is not None:
                out.pieces.add((item.rel, p.part))
                out.how.setdefault(item.rel, "uploaded before by keepgram")
            elif (p.name, p.length) in in_chat:
                out.pieces.add((item.rel, p.part))
                out.how.setdefault(item.rel, "a file with the same name and size is in the chat")
        if item.sha256 in first_of and item.rel not in out.how:
            # The same content twice in this folder.
            for p in item.pieces:
                out.pieces.add((item.rel, p.part))
            out.how[item.rel] = f"same content as {first_of[item.sha256]}"
        first_of.setdefault(item.sha256, item.rel)
    return out


async def send(client, entity, chat_id: int, plan: Plan, skip: set[tuple[str, int]], cfg: dict, state: State,
               cancelled=None):
    as_files = cfg["upload"].get("as_files", True)
    pictures = thumbs.mode(cfg) != "none"
    todo = [(i, p) for i in plan.items for p in i.pieces if (i.rel, p.part) not in skip]
    # media.METER is what progress reports and the screen read; this run keeps
    # its own hold on it, in case another run (the bot runs several) swaps it.
    meter = Meter(sum(p.length for _i, p in todo), len(todo))
    outer, media.METER = media.METER, meter
    try:
        return await _send(client, entity, chat_id, todo, cfg, state, cancelled, as_files, pictures, meter)
    finally:
        media.METER = outer
        from keepgram import transfer

        await transfer.close(client)


async def _send(client, entity, chat_id, todo, cfg, state, cancelled, as_files, pictures, meter):
    problems, done = [], 0
    for n, (item, piece) in enumerate(todo, 1):
        if cancelled and cancelled():
            break
        label = f"[{n}/{len(todo)}] {piece.name if piece.parts > 1 else item.rel}"
        prog = Progress(label)
        try:
            if piece.parts == 1 and not as_files:
                # Photos, videos and songs go up as media and show as Telegram
                # shows them; anything else is a file and gets its picture.
                kind = thumbs.kind_of(item.rel)
                thumb = thumbs.logo(item.rel) if pictures and kind not in ("image", "video", "audio") else None
                msg = await client.send_file(
                    entity, item.path, caption=caption(item, piece), parse_mode=None, silent=True,
                    supports_streaming=True, progress_callback=prog, thumb=thumb,
                )
            else:
                stream = FileSlice(item.path, piece.offset, piece.length, piece.name)
                with stream:
                    picture = thumbs.logo(piece.name) if pictures else None
                    uploaded = await input_media_file(client, stream, piece.name, piece.length, prog, picture)
                msg = await client.send_file(
                    entity, uploaded, caption=caption(item, piece), parse_mode=None, silent=True
                )
                got = msg.media.document.size if isinstance(msg.media, types.MessageMediaDocument) else -1
                if got != piece.length:
                    raise RuntimeError(f"Telegram has {got} bytes, the file {piece.length}")
            state.mark_uploaded(chat_id, item.sha256, piece.part, piece.parts, item.rel, item.size, msg.id)
            prog.end("done")
            done += 1
        except Exception as e:
            prog.end(f"failed: {e}")
            problems.append(f"{piece.name}: {type(e).__name__}: {e}")
        finally:
            meter.finish_unit(piece.length)
    return done, problems
