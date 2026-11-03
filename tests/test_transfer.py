import asyncio
import os
import random
import tempfile
import unittest

from keepgram import media, transfer
from telethon import errors
from telethon.tl import functions, types

from tests import fake

CHAT = -1001111111111
MB = 1024 * 1024


def run(coro):
    return asyncio.run(coro)


class Jittery(fake.FakeClient):
    """Pieces answer in random order, like a real network."""

    def __init__(self):
        super().__init__()
        self.fail_once: set[int] = set()  # piece numbers that hiccup once on the way down
        self.expire_once = False

    async def __call__(self, request, **kw):
        await asyncio.sleep(random.random() / 200)
        if isinstance(request, functions.upload.GetFileRequest):
            index = request.offset // transfer.PART
            if index in self.fail_once:
                self.fail_once.discard(index)
                raise ConnectionError("connection reset")
            if self.expire_once:
                self.expire_once = False
                raise errors.FileReferenceExpiredError(request)
        return await super().__call__(request, **kw)


def doc_message(client, doc_id, size, name="v.mkv"):
    msg = fake.message(CHAT, doc_id, "", fake.doc_media(doc_id, size, name))
    client.chats.setdefault(CHAT, []).append(msg)
    return msg


class Transfers(unittest.TestCase):
    def test_a_big_copy_streams_piece_by_piece_and_comes_out_whole(self):
        client = Jittery()
        msg = doc_message(client, 7, 25 * MB + 12345)
        seen = []
        handle = run(transfer.copy_document(client, msg, "v.mkv", lambda d, t: seen.append((d, t))))
        self.assertIsInstance(handle, types.InputFileBig)
        self.assertEqual(handle.parts, transfer.part_count(25 * MB + 12345))
        self.assertEqual(client.uploaded(handle), client.content(msg.media.document))
        self.assertEqual(seen[-1], (2 * (25 * MB + 12345),) * 2)  # down + up both counted

    def test_a_small_copy_carries_the_md5_telegram_wants(self):
        client = Jittery()
        msg = doc_message(client, 9, 3 * MB + 7)
        handle = run(transfer.copy_document(client, msg, "s.pdf"))
        self.assertIsInstance(handle, types.InputFile)
        self.assertEqual(client.uploaded(handle), client.content(msg.media.document))  # md5 checked in there

    def test_hiccups_are_retried_and_an_expired_link_is_refreshed(self):
        client = Jittery()
        msg = doc_message(client, 11, 6 * MB)
        client.fail_once = {0, 3, 5}
        client.expire_once = True
        handle = run(transfer.copy_document(client, msg, "x.bin"))
        self.assertEqual(client.uploaded(handle), client.content(msg.media.document))

    def test_a_real_failure_stops_the_copy(self):
        class Refuses(Jittery):
            async def __call__(self, request, **kw):
                if isinstance(request, functions.upload.SaveFilePartRequest) and request.file_part == 2:
                    raise errors.FilePartInvalidError(request)
                return await super().__call__(request, **kw)

        client = Refuses()
        msg = doc_message(client, 13, 4 * MB)
        with self.assertRaises(errors.FilePartInvalidError):
            run(transfer.copy_document(client, msg, "x.bin"))

    def test_slows_down_when_telegram_says_so_and_still_arrives_whole(self):
        class Throttled(Jittery):
            floods = 0

            async def __call__(self, request, **kw):
                if (isinstance(request, functions.upload.SaveBigFilePartRequest) and self.floods < 6
                        and random.random() < 0.3):
                    self.floods += 1  # what Telegram sends accounts without Premium
                    raise errors.FloodPremiumWaitError(request, capture=0)
                return await super().__call__(request, **kw)

        client = Throttled()
        msg = doc_message(client, 17, 15 * MB)
        handle = run(transfer.copy_document(client, msg, "x.mkv"))
        self.assertEqual(client.uploaded(handle), client.content(msg.media.document))
        self.assertGreater(client.floods, 0)
        self.assertLess(transfer.gate(client).limit, transfer.UP_AT_ONCE)  # it slowed down

    def test_a_local_copy_is_written_too(self):
        client = Jittery()
        msg = doc_message(client, 15, 2 * MB + 3)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.bin")
            run(transfer.copy_document(client, msg, "x.bin", disk_path=path))
            with open(path, "rb") as f:
                self.assertEqual(f.read(), client.content(msg.media.document))

    def test_uploading_a_slice_of_a_big_file(self):
        client = Jittery()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "movie.mkv")
            data = os.urandom(13 * MB + 99)
            with open(path, "wb") as f:
                f.write(data)
            with media.FileSlice(path, 1 * MB, 12 * MB, "movie.mkv.002") as piece:
                handle = run(transfer.upload(client, piece, 12 * MB, "movie.mkv.002"))
            self.assertIsInstance(handle, types.InputFileBig)
            self.assertEqual(client.uploaded(handle), data[1 * MB:13 * MB])


if __name__ == "__main__":
    unittest.main()
