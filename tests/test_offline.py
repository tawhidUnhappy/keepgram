import asyncio
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from keepgram import config, folders, join, links, media, upload
from keepgram.chats import OwnedChat
from keepgram.state import State
from telethon.tl import types

from tests import fake


class Links(unittest.TestCase):
    def test_kinds(self):
        found = links.find("see t.me/somechan/42 and https://t.me/c/1234567890/7 "
                           "and telegram.me/s/otherchan/5 and t.me/topicchan/3/99 and t.me/joinchat/123 "
                           "and t.me/+abc and t.me/somechan/42")
        self.assertEqual([(lk.username, lk.chat_id, lk.msg_id) for lk in found], [
            ("somechan", None, 42), (None, -1001234567890, 7), ("otherchan", None, 5), ("topicchan", None, 99)])

    def test_strip(self):
        self.assertEqual(links.without_links("  https://t.me/somechan/42 \n"), "")
        self.assertEqual(links.without_links("look t.me/somechan/42"), "look")


class Folders(unittest.TestCase):
    def test_fills_then_makes_the_next(self):
        plans = folders.plan({"Keepgram": list(range(1, 251))}, [], 100)
        self.assertEqual([(p.title, p.action, len(p.peer_ids)) for p in plans],
                         [("Keepgram 1", "create", 100), ("Keepgram 2", "create", 100), ("Keepgram 3", "create", 50)])
        self.assertEqual(len({p.id for p in plans}), 3)
        self.assertTrue(all(2 <= p.id <= 255 for p in plans))

    def test_rerun_keeps_places_and_fills_gaps(self):
        existing = [folders.Existing(2, "Keepgram 1", list(range(1, 101))),
                    folders.Existing(3, "Keepgram 2", list(range(101, 151))),
                    folders.Existing(4, "Work", [999])]
        # chats 1-10 are gone, 151-170 are new
        wanted = list(range(11, 171))
        plans = {p.title: p for p in folders.plan({"Keepgram": wanted}, existing, 100)}
        self.assertNotIn("Work", plans)
        self.assertEqual(plans["Keepgram 1"].removed, list(range(1, 11)))
        self.assertEqual(plans["Keepgram 1"].added, list(range(151, 161)))
        self.assertEqual(plans["Keepgram 2"].added, list(range(161, 171)))
        self.assertEqual(len(plans), 2)

    def test_unchanged_is_keep_and_empty_is_delete(self):
        existing = [folders.Existing(2, "Keepgram 1", [1, 2]), folders.Existing(3, "Keepgram 2", [3])]
        plans = {p.title: p.action for p in folders.plan({"Keepgram": [1, 2]}, existing, 100)}
        self.assertEqual(plans, {"Keepgram 1": "keep", "Keepgram 2": "delete"})

    def test_never_reuses_any_folder_id(self):
        # id 2 is a shared folder (not in `existing`), but it's still taken.
        plans = folders.plan({"Keepgram": [1]}, [folders.Existing(3, "animes", [9])], 100, taken={2, 3, 4})
        self.assertEqual([(p.id, p.action) for p in plans], [(5, "create")])

    def test_name_too_long(self):
        with self.assertRaises(ValueError):
            folders.plan({"Keepgram Arc": [1]}, [], 100)


class PartsAndJoin(unittest.TestCase):
    def test_cut_slice_join_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "movie.mkv"
            data = os.urandom(10_000)
            src.write_bytes(data)
            pieces = upload.cut("movie.mkv", len(data), 3000)
            self.assertEqual([(p.name, p.length) for p in pieces],
                             [("movie.mkv.001", 3000), ("movie.mkv.002", 3000), ("movie.mkv.003", 3000),
                              ("movie.mkv.004", 1000)])
            out = Path(d) / "parts"
            out.mkdir()
            for p in pieces:
                with media.FileSlice(str(src), p.offset, p.length, p.name) as s:
                    self.assertEqual(s.seek(0, 2), p.length)
                    s.seek(0)
                    (out / p.name).write_bytes(s.read())
            joined, digest = join.join(out / "movie.mkv.001")
            self.assertEqual(joined.read_bytes(), data)
            self.assertEqual(digest, hashlib.sha256(data).hexdigest())
            with self.assertRaises(SystemExit):  # never overwrites
                join.join(out / "movie.mkv.001")

    def test_whole_file_is_one_piece(self):
        self.assertEqual(len(upload.cut("a", 3000, 3000)), 1)

    def test_limits(self):
        cfg = config.load()
        cfg["_limits"] = dict(__import__("keepgram.limits", fromlist=["x"]).DEFAULTS)
        self.assertEqual(config.file_limit(cfg), 2000 * config.MB)
        cfg["premium"] = True
        self.assertEqual((config.file_limit(cfg), config.folder_size(cfg)), (4000 * config.MB, 200))


class Thumbnails(unittest.TestCase):
    def test_kinds(self):
        from keepgram import thumbs

        cases = {"[SO] 08 [1080p].mkv": "video", "song.FLAC": "audio", "scan.png": "image", "backup.7z": "archive",
                 "notes.pdf": "document", "app.apk": "app", "movie.mkv.002": "part", "README": "other",
                 "subs.srt": "document"}
        self.assertEqual({n: thumbs.kind_of(n) for n in cases}, cases)
        self.assertEqual(thumbs.kind_of("noext", "video/x-matroska"), "video")
        for kind in thumbs.KINDS:  # every picture exists and Telegram would take it
            path = Path(thumbs.HERE / f"{kind}.jpg")
            self.assertTrue(path.is_file(), kind)
            self.assertLess(path.stat().st_size, 200_000)
            self.assertEqual(path.read_bytes()[:2], b"\xff\xd8")  # JPEG


class Captions(unittest.TestCase):
    def test_note_appended_entities_untouched(self):
        bold = types.MessageEntityBold(0, 4)
        text, ents = media.caption_with_note("Hi 👋 there", [bold], "↪ kept from @x")
        self.assertEqual(text, "Hi 👋 there\n\n↪ kept from @x")
        self.assertEqual(ents, [bold])

    def test_no_room_no_note(self):
        long = "a" * 1020
        self.assertEqual(media.caption_with_note(long, [], "note")[0], long)


def run(coro):
    return asyncio.run(coro)


MINE, OTHER, MINE2 = -1001111111111, -1009999999999, -1002222222222


def owned(chat_id, title):
    return OwnedChat(chat_id, title, "channel", True, fake.channel(chat_id, title, creator=True))


class Secure(unittest.TestCase):
    def setUp(self):
        from keepgram import paths

        self.state = State(Path(tempfile.mkdtemp()) / "state.db")
        paths.TMP = Path(tempfile.mkdtemp())
        self.client = c = fake.FakeClient()
        video = [types.DocumentAttributeVideo(30.0, 1280, 720, supports_streaming=True)]
        c.chats[MINE] = [
            fake.message(MINE, 1, "precious **file**", fake.doc_media(501, 5000, "a.zip"),
                         fwd_from=fake.forwarded_from(OTHER), entities=[types.MessageEntityBold(0, 8)]),
            fake.message(MINE, 2, "", fake.doc_media(502, 10), fwd_from=fake.forwarded_from(MINE2)),
            fake.message(MINE, 3, "album", fake.photo_media(503), fwd_from=fake.forwarded_from(OTHER), grouped_id=7),
            fake.message(MINE, 4, "", fake.doc_media(504, 700, "v.mp4", "video/mp4", video),
                         fwd_from=fake.forwarded_from(OTHER), grouped_id=7),
            fake.message(MINE, 5, "https://t.me/somechan/42"),
            fake.message(MINE, 6, "t.me/lockedchan/1"),
            fake.message(MINE, 7, "mine", fake.doc_media(507, 50)),
        ]
        somechan = fake.channel(-1003333333333, "Some chan", "somechan")
        c.entities["somechan"] = somechan
        c.entities["lockedchan"] = fake.channel(-1004444444444, "Locked", "lockedchan", noforwards=True)
        c.entities[OTHER] = fake.channel(OTHER, "Other people", "otherpeople")
        c.chats[-1003333333333] = [fake.message(-1003333333333, 42, "theirs", fake.doc_media(542, 900, "b.pdf"))]
        self.chats = [owned(MINE, "My stash"), owned(MINE2, "My other")]
        self.cfg = config.load()

    def test_scan_copy_check_replace_and_rerun(self):
        from keepgram import secure

        result = run(secure.scan(self.client, self.chats[:1], {c.id for c in self.chats}, self.cfg, self.state))
        self.assertEqual([[m.id for m in j.own] for j in result.jobs], [[1], [3, 4], [5]])
        self.assertTrue(any("restricted saving" in n for n in result.notes))

        self.cfg["secure"]["replace"] = True
        done, problems = run(secure.run(self.client, result.jobs, self.cfg, self.state))
        self.assertEqual((done, problems), (3, []))
        sent = [m for m, _ in self.client.sent]
        self.assertEqual(sent[0].message, "precious **file**\n\n↪ kept from @otherpeople · 2026-05-01")
        self.assertEqual(sent[0].media.document.size, 5000)
        self.assertIsInstance(sent[1].media, types.MessageMediaPhoto)
        video_attr = next(a for a in self.client.sent[2][1].attributes if isinstance(a, types.DocumentAttributeVideo))
        self.assertEqual((video_attr.w, video_attr.h, video_attr.supports_streaming), (1280, 720, True))
        self.assertFalse(self.client.sent[2][1].force_file)
        self.assertTrue(self.client.sent[0][1].force_file)
        self.assertEqual(sent[3].media.document.size, 900)
        from keepgram import thumbs

        zip_thumb = self.client.sent[0][1].thumb
        self.assertEqual(self.client.uploads[zip_thumb.id], Path(thumbs.logo("a.zip")).read_bytes())
        self.assertIsNone(self.client.sent[2][1].thumb)  # the video goes as a video: Telegram's own preview
        self.assertEqual(sorted(i for _, i in self.client.deleted), [1, 3, 4, 5])

        again = run(secure.scan(self.client, self.chats[:1], {c.id for c in self.chats}, self.cfg, self.state))
        self.assertEqual(again.jobs, [])

    def test_failed_check_records_nothing(self):
        from keepgram import secure

        result = run(secure.scan(self.client, self.chats[:1], {c.id for c in self.chats}, self.cfg, self.state))
        real = self.client.uploaded

        def short(handle):  # Telegram ends up with one byte too few
            return real(handle)[:-1]

        self.client.uploaded = short
        self.cfg["secure"]["replace"] = True
        done, problems = run(secure.run(self.client, result.jobs[:1], self.cfg, self.state))
        self.assertEqual(done, 0)
        self.assertIn("bytes", problems[0])
        self.assertEqual(self.client.deleted, [])
        self.assertFalse(self.state.is_kept(MINE, 1))


class Upload(unittest.TestCase):
    def test_parts_duplicates_and_resume(self):
        state = State(Path(tempfile.mkdtemp()) / "state.db")
        client = fake.FakeClient()
        dest = fake.channel(-1005555555555, "Uploads", creator=True)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "sub").mkdir()
            (root / "a.txt").write_bytes(b"hello")
            big = os.urandom(2500)
            (root / "sub" / "big.bin").write_bytes(big)
            (root / "sub" / "copy.txt").write_bytes(b"hello")
            (root / ".hidden").write_bytes(b"x")
            (root / "empty.txt").write_bytes(b"")
            plan = upload.walk(root, skip_hidden=True)
            self.assertEqual([i.rel for i in plan.items], ["a.txt", "sub/big.bin", "sub/copy.txt"])
            self.assertTrue(any("empty" in s for s in plan.skipped))
            for item in plan.items:
                item.sha256 = upload.sha256_of(item, state)
                item.pieces = upload.cut(Path(item.rel).name, item.size, 1000)

            chat_id = -1005555555555
            first = upload.find_duplicates(plan, chat_id, state, set())
            self.assertEqual(first.how, {"sub/copy.txt": "same content as a.txt"})
            done, problems = run(upload.send(client, dest, chat_id, plan, set(), config.load(), state))
            self.assertEqual((done, problems), (5, []))
            got = [client.uploaded(media.file) for _, media in client.sent]
            self.assertEqual(b"".join(got[1:4]), big)
            self.assertEqual([m.media.document.attributes[0].file_name for m, _ in client.sent],
                             ["a.txt", "big.bin.001", "big.bin.002", "big.bin.003", "copy.txt"])
            self.assertIn("part 2 of 3", client.sent[2][0].message)
            from keepgram import thumbs

            pictures = [client.uploads[media.thumb.id] for _, media in client.sent]
            self.assertEqual(pictures[1], Path(thumbs.HERE / "part.jpg").read_bytes())
            self.assertEqual(pictures[0], Path(thumbs.HERE / "document.jpg").read_bytes())  # a.txt

            # Same folder again: everything is a duplicate, by record and by what's in the chat.
            again = upload.find_duplicates(plan, chat_id, state, set())
            self.assertEqual(len(again.pieces), 5)
            in_chat = run(upload.files_in_chat(client, dest))
            fresh_state = State(Path(tempfile.mkdtemp()) / "state.db")
            from_chat = upload.find_duplicates(plan, chat_id, fresh_state, in_chat)
            self.assertEqual(len(from_chat.pieces), 5)


if __name__ == "__main__":
    unittest.main()


class Limits(unittest.TestCase):
    def test_learned_limits_are_followed(self):
        import asyncio as aio

        from keepgram import limits
        from telethon.tl import types as t

        def num(k, v):
            return t.JsonObjectValue(k, t.JsonNumber(v))

        app_config = t.help.AppConfig(1, t.JsonObject([
            num("upload_max_fileparts_default", 4000), num("upload_max_fileparts_premium", 8000),
            num("dialog_filters_chats_limit_default", 100), num("dialog_filters_chats_limit_premium", 200),
            num("dialog_filters_limit_default", 10), num("dialog_filters_limit_premium", 30),
            num("caption_length_limit_default", 1024), num("caption_length_limit_premium", 4096)]))

        class Client:
            def __init__(self, premium):
                self.premium = premium

            async def __call__(self, request):
                return app_config

            async def get_me(self):
                from types import SimpleNamespace

                return SimpleNamespace(premium=self.premium, bot=False)

        cfg = config.load()
        aio.run(limits.learn(Client(False), cfg))
        self.assertEqual((config.file_limit(cfg), config.folder_size(cfg), limits.folders(cfg)),
                         (2000 * config.MB, 100, 10))
        aio.run(limits.learn(Client(True), cfg))  # got Premium: followed without touching a setting
        self.assertEqual((config.file_limit(cfg), config.folder_size(cfg), limits.folders(cfg), media.CAPTION_LIMIT),
                         (4000 * config.MB, 200, 30, 4096))
        cfg["premium"] = False  # an explicit setting still wins
        self.assertEqual(config.folder_size(cfg), 100)
        cfg["folders"]["size"] = 500  # never more than Telegram allows
        cfg["premium"] = "auto"
        self.assertEqual(config.folder_size(cfg), 200)
        aio.run(limits.learn(Client(False), cfg))


class FolderLimit(unittest.TestCase):
    def test_no_folder_past_the_accounts_limit(self):
        import asyncio as aio

        from telethon.tl import types as t

        from tests.fake import FakeAccount

        client = FakeAccount()
        client.filters = {i: t.DialogFilter(i, t.TextWithEntities(f"f{i}", []), [], [], []) for i in range(2, 11)}
        plans = folders.plan({"Keepgram": [-1001, -1002]}, [], 1, taken=set(client.filters))
        problems = aio.run(folders.apply(client, plans, {}, {}, max_folders=10))
        self.assertEqual(len(client.filters), 10)  # one more fitted, the second didn't
        self.assertIn("may have 10 folders", problems[0])


class SharedLogin(unittest.TestCase):
    def test_every_keepgram_works_on_its_own_copy_of_the_login(self):
        import os
        import sqlite3

        from keepgram import paths, telegram
        from telethon.crypto import AuthKey
        from telethon.sessions import SQLiteSession

        cfg = config.load()
        cfg["api_id"], cfg["api_hash"] = 1, "0" * 32
        if paths.SESSION.exists():
            paths.SESSION.unlink()
        # not logged in yet: logging in uses the login file itself
        self.assertEqual(telegram.make_client(cfg).session.filename, str(paths.SESSION))

        main = SQLiteSession(str(paths.SESSION))
        main.set_dc(5, "149.154.171.5", 443)
        main.auth_key = AuthKey(os.urandom(256))
        main.save()
        main.close()
        holder = sqlite3.connect(str(paths.SESSION))  # another keepgram, between two of its saves
        holder.execute("BEGIN IMMEDIATE")
        try:
            client = telegram.make_client(cfg)
            self.assertEqual(client.session.filename, str(paths.DATA / "sessions" / f"{os.getpid()}.session"))
            self.assertEqual(client.session.auth_key.key, SQLiteSession(str(paths.SESSION)).auth_key.key)
        finally:
            holder.rollback()
            holder.close()

        dead = paths.DATA / "sessions" / "999999999.session"  # left by a keepgram that has ended
        dead.write_bytes(b"")
        telegram.make_client(cfg)
        self.assertFalse(dead.exists())
