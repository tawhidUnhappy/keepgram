"""A stand-in Telegram: real Telethon message types, files kept in memory.
Enough of TelegramClient for secure and upload, nothing more."""

from __future__ import annotations

import datetime as dt
import os
from types import SimpleNamespace

from telethon import utils
from telethon.tl import types

DATE = dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc)


def doc_media(doc_id: int, size: int, name: str = "file.bin", mime="application/octet-stream", attrs=None):
    attributes = [types.DocumentAttributeFilename(name)] + list(attrs or [])
    document = types.Document(doc_id, 1, b"", DATE, mime, size, 2, attributes=attributes, thumbs=None)
    return types.MessageMediaDocument(document=document)


def photo_media(photo_id: int):
    photo = types.Photo(photo_id, 1, b"", DATE, [types.PhotoSize("y", 800, 600, 1234)], 2)
    return types.MessageMediaPhoto(photo=photo)


def message(chat_id: int, msg_id: int, text="", media=None, fwd_from=None, grouped_id=None, entities=None,
            out=True, date=None):
    # out=True: posted by the account itself, as everything in your own channel is.
    peer = utils.resolve_id(chat_id)[1](utils.resolve_id(chat_id)[0])
    return types.Message(msg_id, peer, date or DATE, text, media=media, fwd_from=fwd_from, grouped_id=grouped_id,
                         entities=entities, out=out)


def forwarded_from(chat_id: int):
    return types.MessageFwdHeader(DATE, from_id=utils.resolve_id(chat_id)[1](utils.resolve_id(chat_id)[0]))


def channel(chat_id: int, title: str, username=None, noforwards=False, creator=False):
    real_id, _ = utils.resolve_id(chat_id)
    return types.Channel(real_id, title, None, DATE, creator=creator, username=username, noforwards=noforwards,
                         broadcast=True, access_hash=1)


class FakeClient:
    def __init__(self, me_id=1):
        self.me_id = me_id
        self.chats: dict[int, list] = {}  # chat id -> messages
        self.entities: dict = {}  # id or username -> entity
        self.uploads: dict[int, bytes] = {}
        self.sent: list = []
        self.deleted: list = []
        self._next_upload = 1
        self._next_msg = 10_000
        self.parts: dict[int, dict[int, bytes]] = {}  # file_id -> piece number -> bytes (piece by piece uploads)
        self.part_calls = 0
        self.stored: dict[int, bytes] = {}  # document id -> the bytes it was uploaded with

    # -- reading --
    async def get_me(self):
        return SimpleNamespace(id=self.me_id)

    async def get_entity(self, peer):
        if peer in self.entities:
            return self.entities[peer]
        raise ValueError(f"no entity {peer!r}")

    async def iter_messages(self, entity, reverse=False, filter=None, limit=None):
        msgs = sorted(self.chats.get(utils.get_peer_id(entity), []), key=lambda m: m.id, reverse=not reverse)
        for m in msgs[:limit]:
            yield m

    async def get_messages(self, entity, ids):
        msgs = {m.id: m for m in self.chats.get(utils.get_peer_id(entity), [])}
        if isinstance(ids, list):
            return [msgs.get(i) for i in ids]
        return msgs.get(ids)

    async def download_media(self, msg, file=None, progress_callback=None, thumb=None):
        size = msg.media.document.size if isinstance(msg.media, types.MessageMediaDocument) else 1234
        path = os.path.join(file, f"dl_{msg.id}")
        with open(path, "wb") as f:
            f.write(bytes([msg.id % 256]) * size)
        if progress_callback:
            progress_callback(size, size)
        return path

    # -- writing --
    async def upload_file(self, file, file_size=None, progress_callback=None):
        if isinstance(file, str):
            with open(file, "rb") as f:
                data = f.read()
        else:
            data = b""
            while chunk := file.read(512 * 1024):
                data += chunk
        assert file_size is None or file_size == len(data), (file_size, len(data))
        handle_id = self._next_upload
        self._next_upload += 1
        self.uploads[handle_id] = data
        if progress_callback:
            progress_callback(len(data), len(data))
        return types.InputFile(handle_id, 1, "x", "")

    @staticmethod
    def content(doc) -> bytes:
        """What a fake document holds: a 251-byte pattern of its own, so pieces
        put together in the wrong order don't come out right."""
        block = bytes((doc.id + i) % 256 for i in range(251))
        return (block * (doc.size // 251 + 1))[:doc.size]

    def _document(self, doc_id):
        for msgs in self.chats.values():
            for m in msgs:
                if isinstance(m.media, types.MessageMediaDocument) and m.media.document.id == doc_id:
                    return m.media.document
        raise ValueError(f"no document {doc_id}")

    async def __call__(self, request, **kw):
        from telethon.tl import functions

        if isinstance(request, functions.upload.GetFileRequest):
            doc = self._document(request.location.id)
            data = self.stored[doc.id] if doc.id in self.stored else self.content(doc)
            piece = data[request.offset:request.offset + request.limit]
            return types.upload.File(types.storage.FileUnknown(), 0, piece)
        if isinstance(request, (functions.upload.SaveFilePartRequest, functions.upload.SaveBigFilePartRequest)):
            bytes(request)
            self.part_calls += 1
            self.parts.setdefault(request.file_id, {})[request.file_part] = request.bytes
            return True
        raise NotImplementedError(type(request).__name__)

    def uploaded(self, handle) -> bytes:
        if handle.id in self.uploads:
            return self.uploads[handle.id]
        pieces = self.parts[handle.id]
        assert sorted(pieces) == list(range(handle.parts)), "missing pieces"
        data = b"".join(pieces[i] for i in range(handle.parts))
        if isinstance(handle, types.InputFile) and handle.md5_checksum:
            import hashlib

            assert hashlib.md5(data).hexdigest() == handle.md5_checksum, "md5 doesn't match"
        return data

    def _as_message(self, entity, media, caption):
        self._next_msg += 1
        chat_id = utils.get_peer_id(entity)
        if isinstance(media, types.InputMediaUploadedPhoto):
            out_media = photo_media(self._next_msg)
        else:
            data = self.uploaded(media.file)
            name = next(a.file_name for a in media.attributes if isinstance(a, types.DocumentAttributeFilename))
            out_media = doc_media(self._next_msg, len(data), name, media.mime_type,
                                  [a for a in media.attributes if not isinstance(a, types.DocumentAttributeFilename)])
            self.stored[self._next_msg] = data
        msg = message(chat_id, self._next_msg, caption, media=out_media, date=dt.datetime.now(dt.timezone.utc))
        self.chats.setdefault(chat_id, []).append(msg)
        self.sent.append((msg, media))
        return msg

    async def send_file(self, entity, file, caption=None, formatting_entities=None, parse_mode=(), silent=None,
                        **kwargs):
        assert parse_mode is None, "captions must not be re-parsed"
        if isinstance(file, list):
            return [self._as_message(entity, m, c) for m, c in zip(file, caption, strict=True)]
        return self._as_message(entity, file, caption)

    async def delete_messages(self, entity, ids):
        chat_id = utils.get_peer_id(entity)
        self.deleted += [(chat_id, i) for i in ids]
        self.chats[chat_id] = [m for m in self.chats[chat_id] if m.id not in ids]


class FakeBotClient(FakeClient):
    """FakeClient plus what the bot talks to: its private chats and admin checks."""

    def __init__(self, me_id=77):
        super().__init__(me_id)
        self.admins: dict[int, set[int]] = {}  # chat id -> admin user ids
        self.said: list[tuple[int, str]] = []
        self.history_calls = 0

    async def get_me(self):
        return SimpleNamespace(id=self.me_id, username="keepgram_test_bot")

    async def iter_messages(self, *a, **kw):  # bots can't read history
        self.history_calls += 1
        raise AssertionError("bots can't use messages.getHistory")
        yield  # pragma: no cover

    async def get_permissions(self, chat_id, user_id):
        ok = user_id in self.admins.get(chat_id, set())
        return SimpleNamespace(is_admin=ok, is_creator=False)

    async def send_message(self, user_id, text, buttons=None, parse_mode=None):
        self._next_msg += 1
        self.said.append((user_id, text))
        return SimpleNamespace(id=self._next_msg)

    async def edit_message(self, user_id, msg_id, text, buttons=None, parse_mode=None):
        self.said.append((user_id, text))


class FakeAccount(FakeClient):
    """FakeClient plus the bits the watcher uses: reading after a mark, the
    newest message, and the folder list."""

    def __init__(self, me_id=1):
        super().__init__(me_id)
        self.filters: dict[int, object] = {}

    async def iter_messages(self, entity, reverse=False, filter=None, min_id=0, limit=None):
        msgs = sorted(self.chats.get(utils.get_peer_id(entity), []), key=lambda m: m.id, reverse=not reverse)
        for m in [m for m in msgs if m.id > min_id][:limit]:
            yield m

    async def get_messages(self, entity, ids=None, limit=None):
        if ids is None:
            msgs = sorted(self.chats.get(utils.get_peer_id(entity), []), key=lambda m: m.id, reverse=True)
            return msgs[:limit]
        return await super().get_messages(entity, ids)

    async def __call__(self, request, **kw):
        from telethon.tl import functions

        if isinstance(request, (functions.upload.GetFileRequest, functions.upload.SaveFilePartRequest,
                                functions.upload.SaveBigFilePartRequest)):
            return await FakeClient.__call__(self, request, **kw)
        if isinstance(request, functions.messages.GetDialogFiltersRequest):
            return types.messages.DialogFilters(filters=[types.DialogFilterDefault(), *self.filters.values()])
        if isinstance(request, functions.messages.UpdateDialogFilterRequest):
            bytes(request)
            if request.filter is None:
                self.filters.pop(request.id, None)
            else:
                self.filters[request.id] = request.filter
            return True
        if isinstance(request, functions.messages.GetPeerDialogsRequest):
            bytes(request)
            dialogs = []
            for p in request.peers:
                chat_id = utils.get_peer_id(p.peer)
                top = max((m.id for m in self.chats.get(chat_id, [])), default=0)
                dialogs.append(SimpleNamespace(peer=utils.get_peer(p.peer), top_message=top))
            return SimpleNamespace(dialogs=dialogs)
        raise NotImplementedError(type(request).__name__)

    async def iter_dialogs(self, limit=None):
        for d in getattr(self, "dialogs", [])[:limit]:
            yield d
