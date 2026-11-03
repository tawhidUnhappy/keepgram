"""Stopped at the worst moment - power cut, window closed - and started again:
no file twice, none lost, nothing half-made left behind."""

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path

from keepgram import config, paths, secure
from keepgram.chats import OwnedChat
from keepgram.state import State

from tests import fake

MINE, OTHER = -1001111111111, -1009999999999


def run(coro):
    return asyncio.run(coro)


class PowerCut(Exception):
    """Raised where a real run would simply stop existing."""


class Resume(unittest.TestCase):
    def setUp(self):
        paths.TMP = Path(tempfile.mkdtemp())
        self.state = State(Path(tempfile.mkdtemp()) / "state.db")
        self.client = c = fake.FakeClient()
        c.entities[OTHER] = fake.channel(OTHER, "Other people", "otherpeople")
        self.chat = OwnedChat(MINE, "My stash", "channel", True, fake.channel(MINE, "My stash", creator=True))
        self.cfg = config.load()

    def scan(self):
        return run(secure.scan(self.client, [self.chat], {MINE}, self.cfg, self.state)).jobs

    def test_cut_off_after_posting_before_recording(self):
        self.client.chats[MINE] = [fake.message(MINE, 1, "ep 8", fake.doc_media(501, 5000, "ep8.mkv"),
                                                fwd_from=fake.forwarded_from(OTHER))]
        real = self.state.mark_kept

        def cut(*a, **k):  # the copy is in the chat; the power goes before it's written down
            raise PowerCut

        self.state.mark_kept = cut
        run(secure.run(self.client, self.scan(), self.cfg, self.state))
        self.assertEqual(len(self.client.sent), 1)
        self.state.mark_kept = real

        jobs = self.scan()  # next run: the forward still looks un-copied ...
        self.assertEqual(len(jobs), 1)
        done, problems = run(secure.run(self.client, jobs, self.cfg, self.state))
        self.assertEqual((done, problems), (1, []))
        self.assertEqual(len(self.client.sent), 1)  # ... but its copy is found, not posted again
        self.assertTrue(self.state.is_kept(MINE, 1))
        self.assertEqual(self.scan(), [])  # and nothing is left to do

    def test_cut_off_halfway_through_a_job_of_several_files(self):
        # a forwarded "album" of a photo and a zip can't go as one album: two separate posts
        self.client.chats[MINE] = [
            fake.message(MINE, 1, "", fake.photo_media(501), fwd_from=fake.forwarded_from(OTHER), grouped_id=7),
            fake.message(MINE, 2, "", fake.doc_media(502, 3000, "b.zip"), fwd_from=fake.forwarded_from(OTHER),
                         grouped_id=7),
        ]
        real_send = self.client.send_file
        calls = {"n": 0}

        async def send_then_die(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise PowerCut  # the first file's copy is posted, the second never is
            return await real_send(*a, **k)

        self.client.send_file = send_then_die
        run(secure.run(self.client, self.scan(), self.cfg, self.state))
        self.client.send_file = real_send
        self.assertEqual(len(self.client.sent), 1)

        done, problems = run(secure.run(self.client, self.scan(), self.cfg, self.state))
        self.assertEqual((done, problems), (1, []))
        kinds = sorted(type(m.media).__name__ for m, _ in self.client.sent)
        self.assertEqual(kinds, ["MessageMediaDocument", "MessageMediaPhoto"])  # each exactly once
        self.assertTrue(self.state.is_kept(MINE, 1) and self.state.is_kept(MINE, 2))

    def test_leftover_temporary_folders_are_cleared(self):
        old, fresh = paths.TMP / "old", paths.TMP / "fresh"
        old.mkdir()
        fresh.mkdir()
        (old / "half.mkv").write_bytes(b"x" * 10)
        week_ago = time.time() - 7 * 86400
        os.utime(old, (week_ago, week_ago))
        secure.clean_tmp()
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())  # may belong to a run going on right now


if __name__ == "__main__":
    unittest.main()
