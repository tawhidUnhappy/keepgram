"""verify: every file of an uploaded folder read back from the chat and
compared with the disk, byte for byte - and --fix sending again what isn't."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from keepgram import config, transfer, upload, verify
from keepgram.state import State
from telethon import utils

from tests import fake

CHAT = -1005555555555


def run(coro):
    return asyncio.run(coro)


class Verify(unittest.TestCase):
    def setUp(self):
        self.client = fake.FakeClient()
        self.dest = fake.channel(CHAT, "Uploads", creator=True)
        self.state = State(Path(tempfile.mkdtemp()) / "state.db")
        self.root = Path(tempfile.mkdtemp())
        (self.root / "sub").mkdir()
        self.part = 4 * transfer.PART  # 2 MiB parts: each part is several pieces on the way down
        (self.root / "a.zip").write_bytes(os.urandom(3 * transfer.PART + 777))  # one part, 4 pieces
        (self.root / "sub" / "b.txt").write_bytes(b"hello there")
        (self.root / "sub" / "big.bin").write_bytes(os.urandom(2 * self.part + 12345))  # 3 parts
        self.cfg = config.load()
        self._send_all()

    def _plan(self):
        plan = upload.walk(self.root, skip_hidden=True)
        for item in plan.items:
            item.sha256 = upload.sha256_of(item, self.state)
            item.pieces = upload.cut(Path(item.rel).name, item.size, self.part)
        return plan

    def _send_all(self):
        done, problems = run(upload.send(self.client, self.dest, CHAT, self._plan(), set(), self.cfg, self.state))
        self.assertEqual((done, problems), (5, []))

    def _check(self, state=None):
        orig = upload.part_size
        upload.part_size = lambda cfg: self.part
        try:
            checks = verify.plan_checks(upload.walk(self.root, skip_hidden=True), self.cfg, state or self.state)
            run(verify.check_all(self.client, self.dest, CHAT, checks, state or self.state))
        finally:
            upload.part_size = orig
        return checks

    def _doc_of(self, name):
        return next(m for m in self.client.chats[CHAT] if m.media.document.attributes[0].file_name == name)

    def test_an_upload_reads_back_identical_piece_for_piece(self):
        checks = self._check()
        self.assertEqual(len(checks), 5)  # a.zip, big.bin.001-003, b.txt
        self.assertTrue(all(c.ok for c in checks), [(c.piece.name, c.bad) for c in checks])

    def test_another_device_finds_them_by_name_and_size_then_proves_the_bytes(self):
        fresh = State(Path(tempfile.mkdtemp()) / "state.db")  # no record of the upload
        self.assertTrue(all(c.ok for c in self._check(fresh)))

    def test_one_changed_byte_in_the_chat_is_found(self):
        msg = self._doc_of("big.bin.002")
        data = bytearray(self.client.stored[msg.media.document.id])
        data[transfer.PART + 500] ^= 1  # one bit, in its second piece
        self.client.stored[msg.media.document.id] = bytes(data)
        checks = self._check()
        bad = [c for c in checks if not c.ok]
        self.assertEqual([(c.piece.name, c.bad) for c in bad], [("big.bin.002", [msg.id])])

    def test_a_changed_byte_on_disk_is_found_too(self):
        path = self.root / "a.zip"
        data = bytearray(path.read_bytes())
        data[-1] ^= 0xFF
        path.write_bytes(bytes(data))
        bad = [c.piece.name for c in self._check() if not c.ok]
        self.assertEqual(bad, ["a.zip"])

    def test_a_deleted_message_is_missing(self):
        gone = self._doc_of("b.txt")
        run(self.client.delete_messages(self.dest, [gone.id]))
        bad = [c for c in self._check() if not c.ok]
        self.assertEqual([(c.piece.name, c.bad) for c in bad], [("b.txt", [])])

    def test_fix_sends_again_proves_it_and_deletes_the_different_copy(self):
        broken = self._doc_of("a.zip")
        self.client.stored[broken.media.document.id] = b"\0" * broken.media.document.size
        gone = self._doc_of("b.txt")
        run(self.client.delete_messages(self.dest, [gone.id]))
        orig = upload.part_size
        upload.part_size = lambda cfg: self.part
        try:
            plan = upload.walk(self.root, skip_hidden=True)
            checks = verify.plan_checks(plan, self.cfg, self.state)
            run(verify.check_all(self.client, self.dest, CHAT, checks, self.state))
            self.assertEqual(sorted(c.piece.name for c in checks if not c.ok), ["a.zip", "b.txt"])
            run(verify.fix(self.client, self.dest, CHAT, plan, checks, self.cfg, self.state))
        finally:
            upload.part_size = orig
        self.assertTrue(all(c.ok for c in checks))
        self.assertIn((utils.get_peer_id(self.dest), broken.id), self.client.deleted)
        self.assertTrue(all(c.ok for c in self._check()))  # and a fresh check agrees

    def test_remote_hash_matches_hashlib_whatever_the_order_pieces_arrive_in(self):
        import hashlib

        from tests.test_transfer import Jittery

        jittery = Jittery()  # pieces answer in random order, and two hiccup once
        jittery.chats, jittery.stored = self.client.chats, self.client.stored
        jittery.fail_once = {1, 3}
        msg = self._doc_of("a.zip")
        want = hashlib.sha256(self.client.stored[msg.media.document.id]).hexdigest()
        for at_once in (1, 3, 16):
            self.assertEqual(run(verify.remote_sha256(jittery, msg, at_once=at_once)), want)


if __name__ == "__main__":
    unittest.main()
