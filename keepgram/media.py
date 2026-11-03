"""Files in and out of Telegram: what counts as a file worth keeping, how a
downloaded file goes back up looking the same (name, video size and length,
thumbnail), reading a slice of a big file as its own upload, and progress."""

from __future__ import annotations

import io
import mimetypes
import os
import sys
import time

from telethon.tl import types

# -- what a message holds ----------------------------------------------------

_MEDIA_ATTRS = (types.DocumentAttributeVideo, types.DocumentAttributeAudio, types.DocumentAttributeAnimated)


def has_file(msg) -> bool:
    """A photo or a file - not a sticker, poll, link preview, location, a
    self-destructing photo or paid media."""
    media = getattr(msg, "media", None)
    if isinstance(media, types.MessageMediaPhoto):
        return media.photo is not None and not media.ttl_seconds
    if isinstance(media, types.MessageMediaDocument):
        doc = media.document
        if doc is None or media.ttl_seconds:
            return False
        return not any(isinstance(a, types.DocumentAttributeSticker) for a in doc.attributes)
    return False


def size_of(msg) -> int:
    media = msg.media
    if isinstance(media, types.MessageMediaDocument):
        return media.document.size
    sizes = [getattr(s, "size", 0) or max(getattr(s, "sizes", [0]) or [0]) for s in media.photo.sizes]
    return max(sizes or [0])


def kind_of(msg) -> str:
    """photo | video | audio | file - which messages may share an album."""
    if isinstance(msg.media, types.MessageMediaPhoto):
        return "photo"
    attrs = msg.media.document.attributes
    if any(isinstance(a, types.DocumentAttributeVideo) and not a.round_message for a in attrs):
        return "video"
    if any(isinstance(a, types.DocumentAttributeAudio) and not a.voice for a in attrs):
        return "audio"
    return "file"


def is_plain_file(msg) -> bool:
    """A document sent as a file - not a photo, video, song, voice note or GIF,
    which Telegram shows in their own way."""
    if not isinstance(msg.media, types.MessageMediaDocument):
        return False
    return not any(isinstance(a, _MEDIA_ATTRS) for a in msg.media.document.attributes)


def file_name(msg) -> str:
    doc = msg.media.document
    return next((a.file_name for a in doc.attributes if isinstance(a, types.DocumentAttributeFilename)), "")


def album_ok(msgs) -> bool:
    """Telegram albums: 2-10 items, photos and videos together, or only files,
    or only audio."""
    if not 2 <= len(msgs) <= 10:
        return False
    kinds = {"visual" if k in ("photo", "video") else k for k in map(kind_of, msgs)}
    return len(kinds) == 1


async def input_media_like(client, msg, file, thumb: str | None, progress=None):
    """The same kind of message as `msg`: a photo as a photo, a video with its
    size, length and streaming flag, a file with its name. `file` is a
    downloaded path (uploaded here) or an already uploaded InputFile (a
    streamed copy - transfer.copy_document). Built by hand because Telethon's
    album path drops attributes."""
    if isinstance(file, (types.InputFile, types.InputFileBig)):
        handle = file
    else:
        handle = await client.upload_file(file, progress_callback=progress)
    if isinstance(msg.media, types.MessageMediaPhoto):
        return types.InputMediaUploadedPhoto(file=handle)
    doc = msg.media.document
    attrs = [a for a in doc.attributes if not isinstance(a, types.DocumentAttributeHasStickers)]
    is_media = any(isinstance(a, _MEDIA_ATTRS) for a in attrs)
    is_video = any(isinstance(a, types.DocumentAttributeVideo) for a in attrs)
    return types.InputMediaUploadedDocument(
        file=handle,
        mime_type=doc.mime_type or "application/octet-stream",
        attributes=attrs,
        thumb=await client.upload_file(thumb) if thumb else None,
        force_file=not is_media,
        # Without it, a video with no sound comes back as a GIF.
        nosound_video=True if is_video else None,
    )


async def input_media_file(client, file, name: str, size: int, progress=None, thumb: str | None = None):
    """Any file (a path, or a FileSlice) as a plain file, byte for byte, with
    `thumb` (a JPEG path) as the picture beside it."""
    from keepgram import transfer

    handle = await transfer.upload(client, file, size, name, progress)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return types.InputMediaUploadedDocument(
        file=handle,
        mime_type=mime,
        attributes=[types.DocumentAttributeFilename(name)],
        thumb=await client.upload_file(thumb) if thumb else None,
        force_file=True,
    )


# -- a slice of a file -----------------------------------------------------


class FileSlice(io.RawIOBase):
    """Bytes [offset, offset+length) of a file, read as if it were the whole
    file - so a 9 GB video goes up as 2000 MB parts straight from disk, with
    no copies written anywhere."""

    def __init__(self, path: str, offset: int, length: int, name: str):
        super().__init__()
        self._f = open(path, "rb")  # noqa: SIM115 - closed by close(), like any file object
        self._offset = offset
        self._length = length
        self._pos = 0
        self.name = name

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, pos: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self._length}[whence]
        self._pos = max(0, min(self._length, base + pos))
        return self._pos

    def read(self, n: int = -1) -> bytes:
        left = self._length - self._pos
        n = left if n is None or n < 0 else min(n, left)
        if n <= 0:
            return b""
        self._f.seek(self._offset + self._pos)
        data = self._f.read(n)
        self._pos += len(data)
        return data

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)

    def close(self) -> None:
        self._f.close()
        super().close()


# -- captions ----------------------------------------------------------------

CAPTION_LIMIT = 1024  # 4096 with Premium, but 1024 is safe for every account


def caption_with_note(text: str, entities, note: str | None):
    """The original caption with its formatting, plus a note on its own line
    if there's room. Appending never moves the existing entities."""
    text = text or ""
    entities = list(entities or [])
    if note:
        extra = ("\n\n" if text else "") + note
        if _utf16_len(text + extra) <= CAPTION_LIMIT:
            text += extra
    return text, entities


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def clip(text: str, limit: int = CAPTION_LIMIT) -> str:
    if _utf16_len(text) <= limit:
        return text
    while _utf16_len(text) > limit - 1:
        text = text[:-1]
    return text + "…"


# -- sizes and progress ------------------------------------------------------


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


QUIET = False  # the bot sets it: many jobs at once, and nobody reads the console
# The menus set it: (label, done, total, note) goes to the screen instead of the console.
SINK = None
# A long job sets it (meter.Meter): every file's progress also counts towards the whole.
METER = None


class Progress:
    """One line that redraws itself: label, percent, speed."""

    def __init__(self, label: str):
        self.label = label
        self.start = time.monotonic()
        self.last = 0.0

    def __call__(self, done: int, total: int) -> None:
        if METER is not None:
            METER.partial(self.label, done)
        if SINK:
            SINK(self.label, done, total, None)
            return
        if QUIET:
            return
        now = time.monotonic()
        if done < total and now - self.last < 0.5:
            return
        self.last = now
        speed = done / max(now - self.start, 1e-6)
        pct = 100 * done / total if total else 100
        line = f"  {self.label}  {pct:5.1f}%  {human(done)}/{human(total)}  {human(speed)}/s"
        if METER is not None:
            line += f"  |  all: {METER.summary()}"
        width = _width()
        sys.stdout.write("\r" + line[: width - 1].ljust(width - 1))
        sys.stdout.flush()

    def end(self, note: str = "") -> None:
        if SINK:
            SINK(self.label, 1, 1, note)
            return
        if QUIET:
            return
        width = _width()
        sys.stdout.write("\r" + f"  {self.label}  {note}"[: width - 1].ljust(width - 1) + "\n")
        sys.stdout.flush()


def _width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 100
