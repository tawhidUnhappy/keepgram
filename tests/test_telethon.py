"""Real Telethon, no network: every request keepgram builds is caught where it
would be sent and serialized the way it would go over the wire."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from keepgram import folders, media
from telethon import TelegramClient, utils
from telethon.tl import functions, types

from tests import fake


class Caught(Exception):
    pass


def offline_client(seen):
    client = TelegramClient(None, 1, "0" * 32)

    async def call(sender, request, ordered=False, flood_sleep_threshold=None):
        bytes(request)  # raises if any field has the wrong type
        seen.append(request)
        if isinstance(request, functions.bots.SetBotCommandsRequest):
            return True
        if isinstance(request, functions.messages.UploadMediaRequest):
            if isinstance(request.media, types.InputMediaUploadedPhoto):
                return fake.photo_media(9)
            return fake.doc_media(9, 3)
        raise Caught

    client._call = call
    return client


class RealRequests(unittest.TestCase):
    def setUp(self):
        self.seen = []
        self.client = offline_client(self.seen)
        self.chan = fake.channel(-1001111111111, "Mine", creator=True)
        handle = types.InputFile(1, 1, "x", "")
        video = [types.DocumentAttributeVideo(30.0, 1280, 720, supports_streaming=True),
                 types.DocumentAttributeFilename("v.mp4")]
        self.doc = types.InputMediaUploadedDocument(handle, "video/mp4", video, nosound_video=True)
        self.photo = types.InputMediaUploadedPhoto(handle)

    def send(self, file, caption):
        ents = [[types.MessageEntityBold(0, 1)] for _ in file] if isinstance(file, list) else []
        with self.assertRaises(Caught):
            asyncio.run(self.client.send_file(self.chan, file, caption=caption, formatting_entities=ents,
                                              parse_mode=None, silent=True))

    def test_single_file_keeps_attributes_and_raw_caption(self):
        self.send(self.doc, "a **b** c")
        req = self.seen[-1]
        self.assertIsInstance(req, functions.messages.SendMediaRequest)
        self.assertIs(req.media, self.doc)
        self.assertEqual(req.message, "a **b** c")  # not parsed as markdown
        self.assertTrue(req.silent)

    def test_album(self):
        self.send([self.photo, self.doc], ["one", "two"])
        self.assertIsInstance(self.seen[-1], functions.messages.SendMultiMediaRequest)
        self.assertEqual([m.message for m in self.seen[-1].multi_media], ["one", "two"])

    def test_file_slice_upload(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "big.bin"
            path.write_bytes(b"0123456789" * 1000)
            with media.FileSlice(str(path), 2000, 3000, "big.bin.002") as s, self.assertRaises(Caught):
                asyncio.run(self.client.upload_file(s, file_size=3000))
        part = self.seen[-1]
        self.assertIsInstance(part, functions.upload.SaveFilePartRequest)
        self.assertEqual(part.bytes, (b"0123456789" * 1000)[2000:5000])

    def test_folder_create(self):
        plans = folders.plan({"Keepgram": [utils.get_peer_id(self.chan)]}, [], 100)
        peers = {utils.get_peer_id(self.chan): utils.get_input_peer(self.chan)}

        async def go():
            return await folders.apply(self.client, plans, peers, {})

        async def nothing_yet(request):
            return types.messages.DialogFilters(filters=[types.DialogFilterDefault()])

        real = self.client._call

        async def call(sender, request, ordered=False, flood_sleep_threshold=None):
            if isinstance(request, functions.messages.GetDialogFiltersRequest):
                return await nothing_yet(request)
            return await real(sender, request, ordered, flood_sleep_threshold)

        self.client._call = call
        with self.assertRaises(Caught):
            asyncio.run(go())
        req = self.seen[-1]
        self.assertIsInstance(req, functions.messages.UpdateDialogFilterRequest)
        self.assertEqual(req.filter.title.text, "Keepgram 1")
        self.assertEqual(len(req.filter.include_peers), 1)


class FolderSafety(unittest.TestCase):
    def test_a_shared_folder_is_never_overwritten(self):
        """The first real run: a shared folder sat at id 2, unseen, and got renamed."""
        seen = []
        client = offline_client(seen)
        shared = types.DialogFilterChatlist(2, types.TextWithEntities("Old shared", []), [], [], emoticon="❤")
        real = client._call

        async def call(sender, request, ordered=False, flood_sleep_threshold=None):
            if isinstance(request, functions.messages.GetDialogFiltersRequest):
                return types.messages.DialogFilters(filters=[types.DialogFilterDefault(), shared])
            return await real(sender, request, ordered, flood_sleep_threshold)

        client._call = call
        existing, raw, taken = asyncio.run(folders.read_existing(client))
        self.assertEqual((existing, taken), ([], {2}))
        plans = folders.plan({"Keepgram": [-1001]}, existing, 100, taken)
        self.assertEqual(plans[0].id, 3)
        # and even a stale plan that points at id 2 is refused when applied
        stale = [folders.Planned(2, "Keepgram 1", [-1001], "create", [-1001])]
        problems = asyncio.run(folders.apply(client, stale, {}, {}))
        self.assertIn("already used", problems[0])
        self.assertFalse(any(isinstance(r, functions.messages.UpdateDialogFilterRequest) for r in seen))


class RealBot(unittest.TestCase):
    def test_handlers_commands_and_buttons(self):
        import tempfile as tf
        from types import SimpleNamespace

        from keepgram import bot, config
        from keepgram.botstore import BotStore

        seen = []
        client = offline_client(seen)

        async def me():
            return SimpleNamespace(id=77, username="keepgram_test_bot")

        client.get_me = me
        store = BotStore(Path(tf.mkdtemp()) / "bot.db")
        store.add_chat(-1001, "Stash", "channel", 5)
        kb = bot.KeepBot(client, config.load(), store)
        asyncio.run(kb.setup())
        self.assertTrue(any(isinstance(r, functions.bots.SetBotCommandsRequest) for r in seen))
        self.assertGreaterEqual(len(client.list_event_handlers()), 9)

        said = []

        async def say(user_id, text, buttons, edit):
            said.append((text, buttons))

        async def admin(chat_id, user_id):
            return True

        kb._say, kb.is_admin = say, admin
        asyncio.run(kb.show_panel(5, -1001, None))
        asyncio.run(kb.list_chats(5, None))
        for _text, buttons in said:
            markup = client.build_reply_markup(buttons)
            bytes(markup)  # a real inline keyboard Telegram would accept
            self.assertIsInstance(markup, types.ReplyInlineMarkup)
        urls = [getattr(b.type, "url", None) for row in client.build_reply_markup(kb.add_buttons()).rows
                for b in row.buttons]
        self.assertEqual(urls[0], "https://t.me/keepgram_test_bot?startchannel&admin=post_messages+edit_messages"
                                  "+delete_messages")


if __name__ == "__main__":
    unittest.main()
