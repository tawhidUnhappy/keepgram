import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from keepgram import config, paths, secure, watch
from keepgram.chats import OwnedChat
from keepgram.state import State
from telethon import utils

from tests import fake

MINE, MINE2, OTHER = -1001111111111, -1002222222222, -1009999999999


def run(coro):
    return asyncio.run(coro)


def owned(chat_id, title):
    return OwnedChat(chat_id, title, "channel", True, fake.channel(chat_id, title, creator=True))


class Watch(unittest.TestCase):
    def setUp(self):
        paths.TMP = Path(tempfile.mkdtemp())
        self.state = State(Path(tempfile.mkdtemp()) / "state.db")
        self.client = c = fake.FakeAccount()
        c.entities[OTHER] = fake.channel(OTHER, "Other people", "otherpeople")
        c.chats[MINE] = [
            fake.message(MINE, 1, "", fake.doc_media(1, 100, "old.mkv"), fwd_from=fake.forwarded_from(OTHER)),
            fake.message(MINE, 2, "mine", fake.doc_media(2, 10, "x.bin")),
        ]
        self.cfg = config.load()
        self.w = watch.Watcher(c, self.cfg, self.state)
        self.w.owned = {MINE: owned(MINE, "My stash"), MINE2: owned(MINE2, "Other stash")}
        self.state.set_mark(MINE, 2)  # watching began after message 2

    def post(self, msg_id, size=50, name="new.mkv"):
        msg = fake.message(MINE, msg_id, "", fake.doc_media(msg_id, size, name), fwd_from=fake.forwarded_from(OTHER))
        self.client.chats[MINE].append(msg)

    def test_only_new_forwards_and_never_its_own_copies(self):
        self.post(3)
        run(self.w.check_chat(self.w.owned[MINE]))
        self.assertEqual([m.media.document.size for m, _ in self.client.sent], [50])  # #1, the backlog, isn't copied
        self.assertGreaterEqual(self.state.mark(MINE), 3)
        self.client.sent.clear()
        run(self.w.check_chat(self.w.owned[MINE]))  # its own copy came in as a new message: not a find
        self.assertEqual(self.client.sent, [])

    def test_a_failed_copy_is_tried_again(self):
        self.post(3)
        self.post(4, name="b.mkv")
        real = self.client.upload_file
        calls = {"n": 0}

        async def flaky(file, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("network dropped")
            return await real(file, **kw)

        self.client.upload_file = flaky
        run(self.w.check_chat(self.w.owned[MINE]))
        self.assertEqual(self.state.mark(MINE), 2)  # stays before #3, which failed
        self.assertTrue(self.state.is_kept(MINE, 4))
        run(self.w.check_chat(self.w.owned[MINE]))
        self.assertTrue(self.state.is_kept(MINE, 3))
        self.assertEqual(len(self.client.sent), 2)  # each copied once
        self.assertGreaterEqual(self.state.mark(MINE), 4)

    def test_claimed_by_another_keepgram_is_left_alone(self):
        self.post(3)
        with self.state.db:
            # a claim by another keepgram that is still running (this test's parent stands in for it)
            self.state.db.execute("INSERT INTO claims VALUES (?,?,?,?)", (MINE, 3, os.getppid(), 9e18))
        run(self.w.check_chat(self.w.owned[MINE]))
        self.assertEqual(self.client.sent, [])
        self.assertEqual(self.state.mark(MINE), 2)  # comes back to it

    def test_a_claim_left_by_a_closed_window_is_ignored(self):
        self.post(3)
        dead = subprocess.Popen(["true"])
        dead.wait()  # a process that has ended: its window was closed mid-copy
        with self.state.db:
            self.state.db.execute("INSERT INTO claims VALUES (?,?,?,?)", (MINE, 3, dead.pid, 9e18))
        run(self.w.check_chat(self.w.owned[MINE]))
        self.assertTrue(self.state.is_kept(MINE, 3))

    def test_one_watcher_at_a_time(self):
        first = watch.hold_lock()
        self.assertTrue(watch.watching_elsewhere())
        with self.assertRaises(watch.AlreadyWatching):
            watch.hold_lock()
        first.close()  # the window closes: the lock goes with it
        self.assertFalse(watch.watching_elsewhere())

    def test_new_chats_go_in_folders_and_a_new_folder_when_full(self):
        self.cfg["folders"]["size"] = 2
        run(self.w.sync_folders())
        self.assertEqual(sorted(f.title.text for f in self.client.filters.values()), ["Keepgram 1"])
        third = -1003333333333
        self.w.owned[third] = owned(third, "Brand new")
        run(self.w.sync_folders())
        titles = {f.title.text: [utils.get_peer_id(p) for p in f.include_peers] for f in self.client.filters.values()}
        self.assertEqual(titles["Keepgram 2"], [third])
        del self.w.owned[third]
        run(self.w.sync_folders())  # left it: out of the folders, and the empty folder goes
        self.assertEqual(sorted(f.title.text for f in self.client.filters.values()), ["Keepgram 1"])

    def test_the_minute_check_finds_what_no_update_announced(self):
        from types import SimpleNamespace

        run(self.w._poll_once())
        self.assertTrue(self.w.queue.empty())  # nothing new yet
        self.post(3)  # posted by "your other keepgram": no update reaches the watcher
        made = fake.channel(-1004444444444, "Made just now", creator=True)
        self.client.dialogs = [SimpleNamespace(id=-1004444444444, entity=made)]
        run(self.w._poll_once())
        self.assertEqual(self.w.queue.get_nowait(), MINE)
        self.assertTrue(self.w.folders_due.is_set())  # the new chat: folders are due

    def test_copies_are_recognised_by_their_note(self):
        copy = fake.message(MINE, 9, "theirs\n\n↪ kept from https://t.me/x/1 · 2026-11-02", fake.doc_media(9, 5))
        self.assertTrue(secure.is_keepgram_copy(copy))
        forward = fake.message(MINE, 10, "↪ kept from", fwd_from=fake.forwarded_from(1))
        self.assertFalse(secure.is_keepgram_copy(forward))  # a real forward is never "ours"


if __name__ == "__main__":
    unittest.main()
