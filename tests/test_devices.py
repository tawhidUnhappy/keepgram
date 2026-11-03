"""Started on one device, carried on from another (the phone): what is done is
read from the chats, so nothing is copied twice and nothing lost. And the
forwards that have their own copy can be deleted - only those."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from keepgram import config, paths, secure
from keepgram.chats import OwnedChat
from keepgram.state import State

from tests import fake

MINE, OTHER = -1001111111111, -1009999999999


def run(coro):
    return asyncio.run(coro)


def fresh_state() -> State:
    return State(Path(tempfile.mkdtemp()) / "state.db")


class Devices(unittest.TestCase):
    def setUp(self):
        paths.TMP = Path(tempfile.mkdtemp())
        self.pc = fresh_state()
        self.client = c = fake.FakeClient()
        c.entities[OTHER] = fake.channel(OTHER, "Other people", "otherpeople")
        self.chat = OwnedChat(MINE, "My stash", "channel", True, fake.channel(MINE, "My stash", creator=True))
        self.cfg = config.load()

    def forward(self, msg_id, media, text="", grouped_id=None):
        return fake.message(MINE, msg_id, text, media, fwd_from=fake.forwarded_from(OTHER), grouped_id=grouped_id)

    def scan(self, state):
        return run(secure.scan(self.client, [self.chat], {MINE}, self.cfg, state)).jobs

    def copy_on_pc(self):
        done, problems = run(secure.run(self.client, self.scan(self.pc), self.cfg, self.pc))
        self.assertEqual(problems, [])
        return done

    def test_the_phone_carries_on_without_copying_again(self):
        self.client.chats[MINE] = [self.forward(1, fake.doc_media(501, 5000, "ep1.mkv"), "ep 1"),
                                   self.forward(2, fake.photo_media(502), "poster")]
        self.copy_on_pc()
        self.client.chats[MINE].append(self.forward(3, fake.doc_media(503, 7000, "ep2.mkv"), "ep 2"))

        phone = fresh_state()  # nothing in common with the PC but the chat
        jobs = self.scan(phone)
        self.assertEqual([j.own[0].id for j in jobs], [3])  # only the new one
        self.assertTrue(phone.is_kept(MINE, 1) and phone.is_kept(MINE, 2))
        sent = len(self.client.sent)
        run(secure.run(self.client, jobs, self.cfg, phone))
        self.assertEqual(len(self.client.sent), sent + 1)
        self.assertEqual(self.scan(phone), [])

    def test_half_copied_album_copies_only_the_rest(self):
        self.client.chats[MINE] = [self.forward(1, fake.doc_media(501, 3000, "a.zip"), grouped_id=7),
                                   self.forward(2, fake.doc_media(502, 4000, "b.zip"), grouped_id=7)]
        self.copy_on_pc()
        b_copy = next(m for m, _ in self.client.sent if m.media.document.size == 4000)
        self.client.chats[MINE].remove(b_copy)  # only a.zip's copy made it

        jobs = self.scan(fresh_state())
        self.assertEqual(len(jobs), 1)
        self.assertEqual([f.media.document.size for f in jobs[0].dep.files], [4000])

    def test_the_same_file_from_someone_else_is_not_a_copy(self):
        self.client.chats[MINE] = [
            self.forward(1, fake.doc_media(501, 5000, "ep1.mkv"), "ep 1"),
            fake.message(MINE, 2, "ep 1", fake.doc_media(601, 5000, "ep1.mkv"), out=False),  # a group member's post
        ]
        self.assertEqual([j.own[0].id for j in self.scan(fresh_state())], [1])

    def test_a_photo_needs_keepgrams_note_to_count(self):
        self.client.chats[MINE] = [self.forward(1, fake.photo_media(501)),
                                   fake.message(MINE, 2, "", fake.photo_media(601))]  # just some photo of yours
        self.assertEqual(len(self.scan(fresh_state())), 1)

    def test_delete_forwards_that_have_their_copy(self):
        self.client.chats[MINE] = [self.forward(1, fake.doc_media(501, 5000, "ep1.mkv"), "ep 1"),
                                   self.forward(2, fake.photo_media(502), "poster"),
                                   self.forward(3, fake.doc_media(503, 6000, "ep2.mkv"), "ep 2")]
        self.copy_on_pc()
        copies = [m.id for m, _ in self.client.sent]
        self.client.chats[MINE].append(self.forward(4, fake.doc_media(504, 8000, "ep3.mkv")))  # no copy yet

        phone = fresh_state()
        self.scan(phone)
        plan, notes = run(secure.tidy_plan(self.client, [self.chat], phone))
        self.assertEqual(notes, [])
        self.assertEqual(plan[0].forwards, [1, 2, 3])
        self.assertEqual(run(secure.tidy(self.client, plan, phone)), 3)

        left = sorted(m.id for m in self.client.chats[MINE])
        self.assertEqual(left, [4, *copies])  # the copies stay, and the forward without one
        self.assertEqual(run(secure.tidy_plan(self.client, [self.chat], phone)), ([], []))
        self.assertEqual([j.own[0].id for j in self.scan(phone)], [4])

    def test_a_forward_whose_copy_is_gone_is_kept_and_copied_again(self):
        self.client.chats[MINE] = [self.forward(1, fake.doc_media(501, 5000, "ep1.mkv"), "ep 1")]
        self.copy_on_pc()
        copy = self.client.sent[0][0]
        self.client.chats[MINE].remove(copy)

        plan, notes = run(secure.tidy_plan(self.client, [self.chat], self.pc))
        self.assertEqual(plan, [])
        self.assertEqual(len(notes), 1)
        self.assertEqual(self.client.deleted, [])
        self.assertEqual([j.own[0].id for j in self.scan(self.pc)], [1])


if __name__ == "__main__":
    unittest.main()
