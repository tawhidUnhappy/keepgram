import asyncio
import tempfile
import unittest
from pathlib import Path

from keepgram import bot, config, paths
from keepgram.botstore import BotStore

from tests import fake

CHAN, OTHER, ADMIN, STRANGER = -1001111111111, -1009999999999, 500, 600


def run(coro):
    return asyncio.run(coro)


class Bot(unittest.TestCase):
    def setUp(self):
        paths.TMP = Path(tempfile.mkdtemp())
        self.client = c = fake.FakeBotClient()
        c.entities[CHAN] = fake.channel(CHAN, "My stash")
        c.entities[OTHER] = fake.channel(OTHER, "Other people", "otherpeople")
        c.admins[CHAN] = {ADMIN}
        # message numbers with a long gap of deleted ones in between
        c.chats[CHAN] = [
            fake.message(CHAN, 3, "", fake.doc_media(1, 4000, "a.zip"), fwd_from=fake.forwarded_from(OTHER)),
            fake.message(CHAN, 250, "mine", fake.doc_media(2, 10)),
            fake.message(CHAN, 1900, "", fake.doc_media(3, 777, "b.zip"), fwd_from=fake.forwarded_from(OTHER)),
        ]
        self.store = BotStore(Path(tempfile.mkdtemp()) / "bot.db")
        self.bot = bot.KeepBot(c, config.load(), self.store)
        self.bot.me = run(c.get_me())
        self.store.add_chat(CHAN, "My stash", "channel", ADMIN)

    def test_reads_by_number_across_gaps(self):
        async def collect():
            return [m.id async for m in bot.messages_by_id(self.client, self.client.entities[CHAN], 0)]

        self.assertEqual(run(collect()), [3, 250, 1900])

    def test_keep_all_copies_and_reports(self):
        chat = self.store.chat(CHAN)
        self.bot.running.clear()
        run(self.bot.keep_all(chat, ADMIN))
        self.assertEqual(self.client.history_calls, 0)
        sizes = [m.media.document.size for m, _ in self.client.sent]
        self.assertEqual(sizes, [4000, 777])
        self.assertEqual(self.store.kept_in(CHAN), 2)
        self.assertIn("kept 2 of 2", self.client.said[-1][1])
        self.assertEqual(self.client.deleted, [])  # delete-forwards is off by default

        # again: nothing new, and its own copies aren't read as finds
        self.client.sent.clear()
        run(self.bot.keep_all(self.store.chat(CHAN), ADMIN))
        self.assertEqual(self.client.sent, [])

    def test_auto_keep_with_delete(self):
        self.store.set_flag(CHAN, "replace", True)
        new = fake.message(CHAN, 2000, "", fake.doc_media(4, 55, "c.zip"), fwd_from=fake.forwarded_from(OTHER))
        self.client.chats[CHAN].append(new)
        run(self.bot.auto_keep(self.store.chat(CHAN), [new]))
        self.assertEqual([m.media.document.size for m, _ in self.client.sent], [55])
        self.assertEqual(self.client.deleted, [(CHAN, 2000)])

    def test_only_admins_get_the_panel(self):
        run(self.bot.show_panel(STRANGER, CHAN, None))
        self.assertIn("Only admins", self.client.said[-1][1])
        run(self.bot.show_panel(ADMIN, CHAN, None))
        self.assertIn("Auto-keep new forwards", self.client.said[-1][1])

    def test_forwards_between_one_persons_chats_are_skipped(self):
        self.store.add_chat(OTHER, "Other people", "channel", ADMIN)
        run(self.bot.keep_all(self.store.chat(CHAN), ADMIN))
        self.assertEqual(self.client.sent, [])


if __name__ == "__main__":
    unittest.main()
