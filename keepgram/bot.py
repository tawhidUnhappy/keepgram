"""keepgram as a Telegram bot anyone can use: add it to your channel or group
as an admin and it keeps the files there your own.

    Keep all old files   reads the chat by message number (bots can't read
                         history the way accounts do) and copies every
                         forward / post-link file as a new post, like `secure`
    Auto-keep            new forwards are copied the moment they're posted
    Remove forwards      the forward is deleted once its copy is checked

Everything is managed in a private chat with the bot, by the chat's admins
only. Bots can't touch chat folders or your disk, so `folders` and `upload`
stay in the app (./run.sh).

Telegram's rules for bots decide the shape of this: messages.getHistory,
messages.getDialogs and messages.updateDialogFilter are "only users", while
channels.getMessages / messages.getMessages (by id), channels.getParticipant
and big file uploads are "both users and bots"."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import getpass
import html
import time
from dataclasses import dataclass, field

from telethon import Button, TelegramClient, errors, events, utils
from telethon.tl import functions, types

from keepgram import __version__, config, media, paths, secure
from keepgram.botstore import BotChat, BotStore
from keepgram.chats import OwnedChat

# Admin rights asked for by the "Add to ..." buttons (Telegram fills them in).
CHANNEL_RIGHTS = "post_messages+edit_messages+delete_messages"
GROUP_RIGHTS = "delete_messages"

# Reading by number: after the newest message seen, stop at this many empty
# batches of 100 in a row (gaps left by deleted messages).
BATCH = 100
GAP_BATCHES = 20
TICK = 4.0  # seconds between progress edits


async def messages_by_id(client, entity, top_hint: int, cancelled=None):
    """Every message of a chat, oldest first, fetched 100 numbers at a time."""
    start, empty_run = 1, 0
    while True:
        if cancelled and cancelled():
            return
        got = await client.get_messages(entity, ids=list(range(start, start + BATCH)))
        found = [m for m in got if m is not None and not isinstance(m, types.MessageEmpty)]
        for m in found:
            yield m
        start += BATCH
        empty_run = 0 if found else empty_run + 1
        if start > top_hint and empty_run >= GAP_BATCHES:
            return


@dataclass
class Running:
    chat_id: int
    user_id: int
    stop: bool = False
    status: str = "starting"
    done: int = 0
    found: int = 0
    read: int = 0
    started: float = field(default_factory=time.monotonic)


class KeepBot:
    def __init__(self, client, cfg: dict, store: BotStore):
        self.client = client
        self.cfg = copy.deepcopy(cfg)
        self.cfg["premium"] = False  # bots get the free limits
        self.store = store
        self.running: dict[int, Running] = {}
        self.slots = asyncio.Semaphore(max(1, int(self.cfg["bot"].get("max_jobs") or 1)))
        self.me = None

    # -- wiring ------------------------------------------------------------

    async def setup(self) -> None:
        self.me = await self.client.get_me()
        c = self.client
        c.add_event_handler(self.on_start, events.NewMessage(pattern=r"^/start(?:@\w+)?(?:\s+(\S+))?$",
                                                             func=lambda e: e.is_private))
        c.add_event_handler(self.on_chats, events.NewMessage(pattern=r"^/chats(?:@\w+)?$", func=lambda e: e.is_private))
        c.add_event_handler(self.on_help, events.NewMessage(pattern=r"^/help(?:@\w+)?$", func=lambda e: e.is_private))
        c.add_event_handler(self.on_private_forward, events.NewMessage(func=lambda e: e.is_private and e.fwd_from))
        c.add_event_handler(self.on_button, events.CallbackQuery())
        c.add_event_handler(self.on_channel_participant, events.Raw(types.UpdateChannelParticipant))
        c.add_event_handler(self.on_chat_action, events.ChatAction())
        c.add_event_handler(self.on_new_message, events.NewMessage(func=lambda e: not e.is_private))
        c.add_event_handler(self.on_album, events.Album(func=lambda e: not e.is_private))
        with contextlib.suppress(errors.RPCError):  # cosmetic
            await c(functions.bots.SetBotCommandsRequest(
                scope=types.BotCommandScopeDefault(), lang_code="",
                commands=[types.BotCommand("start", "add me to a channel or group"),
                          types.BotCommand("chats", "your chats with me in them"),
                          types.BotCommand("help", "what I do")]))

    def allowed(self, user_id: int) -> bool:
        allowed = self.cfg["bot"].get("allowed_users") or []
        return not allowed or user_id in allowed

    # -- private chat ------------------------------------------------------

    def add_buttons(self):
        name = self.me.username
        return [[Button.url("➕ Add me to a channel", f"https://t.me/{name}?startchannel&admin={CHANNEL_RIGHTS}")],
                [Button.url("➕ Add me to a group", f"https://t.me/{name}?startgroup=keepgram&admin={GROUP_RIGHTS}")],
                [Button.inline("📋 My chats", b"chats")]]

    async def on_start(self, event):
        if not self.allowed(event.sender_id):
            await event.respond("This keepgram bot is private.")
            return
        payload = event.pattern_match.group(1)
        if payload and payload.startswith("chat_") and payload[5:].lstrip("-").isdigit():
            await self.show_panel(event.sender_id, int(payload[5:]), None)
            return
        await event.respond(
            "<b>keepgram</b> keeps the files in your channels and groups <b>your own</b>.\n\n"
            "Files forwarded from other chats, and links to other people's posts, vanish when the original "
            "or its account is deleted. I post each of those files again as a new post of the chat itself, "
            "so it stays.\n\n"
            "1. Add me to your channel or group as an admin (the buttons ask Telegram for the right "
            "permissions).\n"
            "2. Open <b>My chats</b> here, or forward me any post from the channel.\n"
            "3. Tap <b>Keep all old files</b>. New forwards are kept automatically.",
            buttons=self.add_buttons(), parse_mode="html")

    async def on_help(self, event):
        await self.on_start(event)

    async def on_chats(self, event):
        await self.list_chats(event.sender_id, None)

    async def list_chats(self, user_id: int, edit_msg_id: int | None):
        chats = self.store.chats_of(user_id)
        if chats:
            text = "Your chats with me in them - tap one:"
            buttons = [[Button.inline(f"{'📢' if c.kind == 'channel' else '👥'} {c.title}"[:60],
                                      f"panel:{c.chat_id}".encode())] for c in chats[:50]]
        else:
            text = ("I'm not in any chat of yours yet. Add me with a button below - or, if I'm already in "
                    "your channel, forward me any post from it.")
            buttons = []
        buttons += self.add_buttons()[:2]
        await self._say(user_id, text, buttons, edit_msg_id)

    async def on_private_forward(self, event):
        """A post forwarded from a channel opens that channel's panel."""
        if not self.allowed(event.sender_id):
            return
        fwd = event.fwd_from
        if not isinstance(fwd.from_id, types.PeerChannel):
            await event.respond("Forward me a post from your channel, or use /chats.")
            return
        chat_id = utils.get_peer_id(fwd.from_id)
        if fwd.channel_post:
            self.store.bump_top(chat_id, fwd.channel_post)
        if self.store.chat(chat_id) is None:
            await event.respond("I'm not in that channel yet - add me as an admin first.",
                                buttons=self.add_buttons()[:1])
            return
        await self.show_panel(event.sender_id, chat_id, None)

    # -- the panel ---------------------------------------------------------

    async def is_admin(self, chat_id: int, user_id: int) -> bool:
        try:
            perms = await self.client.get_permissions(chat_id, user_id)
            return bool(perms.is_admin or perms.is_creator)
        except (errors.RPCError, ValueError, TypeError):
            return False

    async def show_panel(self, user_id: int, chat_id: int, edit_msg_id: int | None):
        chat = self.store.chat(chat_id)
        if chat is None:
            await self._say(user_id, "I'm not in that chat any more.", None, edit_msg_id)
            return
        if not await self.is_admin(chat_id, user_id):
            await self._say(user_id, f"Only admins of {chat.title} can manage me there.", None, edit_msg_id)
            return
        self.store.add_manager(chat_id, user_id)
        job = self.running.get(chat_id)
        on, off = "✅ on", "❌ off"
        text = (f"{'📢' if chat.kind == 'channel' else '👥'} <b>{html.escape(chat.title)}</b>\n\n"
                f"Auto-keep new forwards: {on if chat.auto else off}\n"
                f"Delete the forward after copying: {on if chat.replace else off}\n"
                f"Files kept here so far: {self.store.kept_in(chat_id)}")
        if job:
            text += f"\n\n⏳ {job.status}"
        first = (Button.inline("⏹ Stop", f"stop:{chat_id}".encode()) if job
                 else Button.inline("🔒 Keep all old files now", f"keep:{chat_id}".encode()))
        buttons = [
            [first],
            [Button.inline(f"Auto-keep: {'on' if chat.auto else 'off'}", f"auto:{chat_id}".encode()),
             Button.inline(f"Delete forwards: {'on' if chat.replace else 'off'}", f"repl:{chat_id}".encode())],
            [Button.inline("🔄 Refresh", f"panel:{chat_id}".encode()), Button.inline("« My chats", b"chats")],
        ]
        await self._say(user_id, text, buttons, edit_msg_id)

    async def on_button(self, event):
        user_id = event.sender_id
        if not self.allowed(user_id):
            await event.answer("This keepgram bot is private.", alert=True)
            return
        data = event.data.decode()
        msg_id = event.message_id
        if data == "chats":
            await event.answer()
            await self.list_chats(user_id, msg_id)
            return
        action, _, raw = data.partition(":")
        if not raw.lstrip("-").isdigit():
            await event.answer()
            return
        chat_id = int(raw)
        if action != "panel" and not await self.is_admin(chat_id, user_id):
            await event.answer("Only that chat's admins can do this.", alert=True)
            return
        chat = self.store.chat(chat_id)
        if action == "auto" and chat:
            self.store.set_flag(chat_id, "auto", not chat.auto)
        elif action == "repl" and chat:
            self.store.set_flag(chat_id, "replace", not chat.replace)
        elif action == "stop" and chat_id in self.running:
            self.running[chat_id].stop = True
            await event.answer("Stopping after the current file.")
        elif action == "keep" and chat:
            if chat_id in self.running:
                await event.answer("Already running.")
            else:
                await event.answer("Starting.")
                asyncio.create_task(self.keep_all(chat, user_id))
                await asyncio.sleep(0.2)
        await self.show_panel(user_id, chat_id, msg_id)
        with contextlib.suppress(errors.RPCError):  # already answered
            await event.answer()

    # -- joining and leaving chats -------------------------------------------

    async def on_channel_participant(self, update: types.UpdateChannelParticipant):
        if update.user_id != self.me.id:
            return
        chat_id = utils.get_peer_id(types.PeerChannel(update.channel_id))
        p = update.new_participant
        if p is None or isinstance(p, (types.ChannelParticipantBanned, types.ChannelParticipantLeft)):
            self.store.remove_chat(chat_id)
            return
        await self.joined(chat_id, update.actor_id)

    async def on_chat_action(self, event):
        if event.user_added and self.me.id in (event.user_ids or []):
            await self.joined(event.chat_id, getattr(event.added_by, "id", None) or event.sender_id)
        elif (event.user_kicked or event.user_left) and self.me.id in (event.user_ids or []):
            self.store.remove_chat(event.chat_id)

    async def joined(self, chat_id: int, by: int | None):
        try:
            entity = await self.client.get_entity(chat_id)
        except (ValueError, errors.RPCError):
            return
        kind = "channel" if isinstance(entity, types.Channel) and entity.broadcast else "group"
        new = self.store.add_chat(chat_id, entity.title, kind, by)
        if new and by:
            try:
                await self.client.send_message(by, f"I'm in <b>{html.escape(entity.title)}</b> now.",
                                               parse_mode="html")
                await self.show_panel(by, chat_id, None)
            except (errors.RPCError, ValueError):
                pass  # they never opened a chat with me - /start then /chats finds it

    # -- auto-keep -------------------------------------------------------------

    async def on_new_message(self, event):
        msg = event.message
        chat = self.store.chat(event.chat_id)
        if chat is None:
            return
        self.store.bump_top(chat.chat_id, msg.id)
        if chat.auto and not msg.grouped_id and not msg.out:
            await self.auto_keep(chat, [msg])

    async def on_album(self, event):
        chat = self.store.chat(event.chat_id)
        if chat is not None and chat.auto:
            await self.auto_keep(chat, [m for m in event.messages if not m.out])

    async def auto_keep(self, chat: BotChat, msgs: list):
        if not msgs or chat.chat_id in self.running:
            return  # a full run is going through this chat anyway

        async def given(_chat):
            for m in msgs:
                yield m

        target = await self._owned(chat)
        cfg = self._cfg_for(chat)
        result = await secure.scan(self.client, [target], self.store.managed_together(chat.chat_id), cfg,
                                   self.store, messages=given, progress=lambda r: None)
        if result.jobs:
            await secure.run(self.client, result.jobs, cfg, self.store, report=lambda *a: None)

    # -- keep all old files ------------------------------------------------------

    async def keep_all(self, chat: BotChat, user_id: int):
        job = self.running[chat.chat_id] = Running(chat.chat_id, user_id)
        status = await self.client.send_message(user_id, f"⏳ {chat.title}: waiting for a free slot ...")
        ticker = asyncio.create_task(self._tick(job, chat, status.id))
        problems, notes, total = [], [], 0
        try:
            async with self.slots:
                target = await self._owned(chat)
                cfg = self._cfg_for(chat)

                def progress(result):
                    job.read, job.found = result.messages, sum(len(j.dep.files) for j in result.jobs)
                    job.status = f"reading: {job.read} messages, {job.found} file(s) to keep"

                job.status = "reading the chat ..."
                result = await secure.scan(
                    self.client, [target], self.store.managed_together(chat.chat_id), cfg, self.store,
                    messages=lambda c: messages_by_id(self.client, c.entity, chat.top_id, lambda: job.stop),
                    progress=progress, cancelled=lambda: job.stop)
                job.read, notes, total = result.messages, result.notes, len(result.jobs)

                def report(n, count, _j):
                    job.status = f"copying {n} of {count} ..."

                job.done, problems = await secure.run(self.client, result.jobs, cfg, self.store, report=report,
                                                      cancelled=lambda: job.stop)
        except Exception as e:
            problems.append(f"{type(e).__name__}: {e}")
        finally:
            ticker.cancel()
            self.running.pop(chat.chat_id, None)
        lines = [f"{'⏹ Stopped' if job.stop else '✅ Done'}: <b>{html.escape(chat.title)}</b>",
                 f"Read {job.read} messages; kept {job.done} of {total} as the chat's own."]
        if not total and not job.stop:
            lines.append("Nothing depended on anyone else.")
        for line in (problems + notes)[:8]:
            lines.append("• " + html.escape(line))
        if len(problems) + len(notes) > 8:
            lines.append(f"• ... and {len(problems) + len(notes) - 8} more")
        if problems:
            lines.append("Tap Keep all old files again to retry what failed.")
        await self._say(user_id, "\n".join(lines), [[Button.inline("Back to the chat",
                                                                    f"panel:{chat.chat_id}".encode())]], status.id)

    async def _tick(self, job: Running, chat: BotChat, msg_id: int):
        last = ""
        while True:
            await asyncio.sleep(TICK)
            text = f"⏳ {chat.title}: {job.status}"
            if text != last:
                last = text
                await self._say(job.user_id, text, [[Button.inline("⏹ Stop", f"stop:{chat.chat_id}".encode())]],
                                msg_id)

    # -- helpers -----------------------------------------------------------------

    async def _owned(self, chat: BotChat) -> OwnedChat:
        entity = await self.client.get_entity(chat.chat_id)
        return OwnedChat(chat.chat_id, chat.title, chat.kind, False, entity)

    def _cfg_for(self, chat: BotChat) -> dict:
        cfg = copy.deepcopy(self.cfg)
        cfg["secure"]["replace"] = chat.replace
        cfg["secure"]["local_copy_dir"] = ""  # the host keeps nobody's files
        return cfg

    async def _say(self, user_id: int, text: str, buttons, edit_msg_id: int | None):
        try:
            if edit_msg_id:
                await self.client.edit_message(user_id, edit_msg_id, text, buttons=buttons, parse_mode="html")
            else:
                await self.client.send_message(user_id, text, buttons=buttons, parse_mode="html")
        except errors.MessageNotModifiedError:
            pass
        except errors.RPCError as e:
            print(f"  [bot] couldn't message {user_id}: {e}")


async def start(cfg: dict, ask_token=None):
    """Connect as the bot and wire it up; returns (client, bot, store).
    ask_token() is awaited for a token when config.json has none."""
    if not cfg.get("api_id") or not cfg.get("api_hash"):
        raise SystemExit("No api_id / api_hash yet - log in first (or put them in config.json)")
    token = cfg["bot"].get("token")
    if not token:
        token = (await ask_token()) if ask_token else None
        if not token:
            raise SystemExit("No bot token - make a bot with @BotFather (/newbot) first")
        cfg["bot"]["token"] = token.strip()
        config.save(cfg)
    media.QUIET = True
    paths.DATA.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(paths.BOT_SESSION), int(cfg["api_id"]), cfg["api_hash"],
                            flood_sleep_threshold=24 * 3600, device_model="keepgram bot", app_version=__version__)
    await client.start(bot_token=cfg["bot"]["token"])
    from keepgram import telegram

    await telegram.listen(client)  # or a restarted bot hears nothing
    store = BotStore(paths.BOT_STATE)
    bot = KeepBot(client, cfg, store)
    await bot.setup()
    return client, bot, store


async def serve(cfg: dict) -> None:
    async def ask_token():
        print("Make a bot with @BotFather (/newbot) and paste its token here. It is saved in", paths.CONFIG)
        return getpass.getpass("bot token (hidden): ")

    client, bot, store = await start(cfg, ask_token)
    print(f"keepgram bot @{bot.me.username} is running, in {store.chat_count()} chat(s). Ctrl+C stops it.")
    print(f"  https://t.me/{bot.me.username}")
    try:
        await client.run_until_disconnected()
    finally:
        store.close()
