"""What each menu item does: dialogs and task screens one after another, the
same library calls the commands make (cli.py), only shown on screen."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from telethon import errors, utils

from keepgram import bot as botmod
from keepgram import chats, config, folders, join, limits, paths, plugins, secure, telegram, upload
from keepgram.media import human
from keepgram.state import State
from keepgram.ui.dialogs import Ask, Choice, Result
from keepgram.ui.task import Outcome, TaskScreen

HOME = "keepgram"


async def task(app, where: str, title: str, work) -> Outcome:
    return await app.push_screen_wait(TaskScreen([HOME, where], title, work))


async def failed(app, title: str, out: Outcome) -> bool:
    """Show a failed task's error; True if it failed."""
    if out.ok:
        return False
    await app.push_screen_wait(Result(title, out.error or "Stopped.", ok=False))
    return True


def _home_info(app) -> None:
    from keepgram.ui.screens import HomeScreen

    for screen in app.screen_stack:
        if isinstance(screen, HomeScreen):
            screen.refresh_info()


# -- the account -------------------------------------------------------------------


async def quiet_connect(app) -> None:
    """At start: connect with the saved login if there is one, asking nothing."""
    if not app.cfg.get("api_id") or not paths.SESSION.is_file():
        return
    client = telegram.make_client(app.cfg)
    await client.connect()
    if await client.is_user_authorized():
        app.client, app.me = client, await client.get_me()
        await limits.learn(client, app.cfg)
        _home_info(app)
    else:
        await client.disconnect()


async def ensure_client(app):
    """The connected client - logging in first (in dialogs) if needed."""
    if app.client is not None and app.client.is_connected():
        return app.client
    cfg = app.cfg
    if not cfg.get("api_id") or not cfg.get("api_hash"):
        note = ("keepgram logs in as you through an API app of your own: open https://my.telegram.org, "
                "log in, API development tools, create an app (platform: Desktop).")
        api_id = await app.push_screen_wait(Ask("Your api_id", note, placeholder="a number like 12345678"))
        if not api_id or not api_id.strip().isdigit():
            raise SystemExit("Logging in needs the api_id from my.telegram.org.")
        api_hash = await app.push_screen_wait(Ask("Your api_hash", "From the same page. It stays on this computer.",
                                                  password=True))
        if not api_hash:
            raise SystemExit("Logging in needs the api_hash from my.telegram.org.")
        cfg["api_id"], cfg["api_hash"] = int(api_id.strip()), api_hash.strip()
        config.save(cfg)
    client = telegram.make_client(cfg)
    await client.connect()
    if not await client.is_user_authorized():
        # Log in on the login file itself (not this keepgram's copy of it).
        await client.disconnect()
        client = telegram.make_client(cfg, paths.SESSION)
        await client.connect()

        async def ask(title, note, password=False):
            value = await app.push_screen_wait(Ask(title, note, password=password))
            if value is None:
                raise SystemExit("Login cancelled.")
            return value.strip()

        try:
            await client.start(
                phone=lambda: ask("Log in: phone number", "With the country code, like +8801…"),
                code_callback=lambda: ask("Log in: the code", "Telegram just sent it to your Telegram app."),
                password=lambda: ask("Log in: your cloud password", "Two-step verification is on.", True),
            )
        except BaseException:
            await client.disconnect()
            raise
        telegram._lock_session()
    app.client, app.me = client, await client.get_me()
    await limits.learn(client, cfg)
    _home_info(app)
    return client


async def account_flow(app) -> None:
    if app.me is None:
        await ensure_client(app)
        await app.push_screen_wait(Result("Logged in", f"Logged in as {utils.get_display_name(app.me)}.\n\n"
                                          f"The login is kept in {paths.SESSION} - it opens your account, "
                                          "never share it."))
        return
    pick = await app.push_screen_wait(Choice(
        f"Logged in as {utils.get_display_name(app.me)}", "Logging out ends keepgram's login everywhere; "
        "your Telegram apps stay logged in.", [("stay", "Stay logged in"), ("out", "Log out of keepgram")],
        default="stay"))
    if pick == "out":
        await app.client.log_out()
        app.client = app.me = None
        _home_info(app)
        await app.push_screen_wait(Result("Logged out", "keepgram is logged out."))


async def load_chats(app, screen) -> None:
    client = await ensure_client(app)
    screen.show(await chats.owned_chats(client, app.cfg["include_admin_chats"]))


async def chat_flow(app, chat) -> None:
    pick = await app.push_screen_wait(Choice(chat.title, f"{chat.kind}, id {chat.id}", [
        ("secure", "Make every file here my own"),
        ("upload", "Upload a folder into it"),
        ("back", "Back")]))
    if pick == "secure":
        await secure_flow(app, only=chat.id)
    elif pick == "upload":
        await upload_flow(app, into=chat)


# -- folders -----------------------------------------------------------------------


async def folders_flow(app) -> None:
    client = await ensure_client(app)
    cfg = app.cfg

    async def make_plan(t):
        t.step("reading your chats and folders ...")
        owned = await chats.owned_chats(client, cfg["include_admin_chats"])
        plugins.load()
        groups = plugins.get("sorter", cfg["folders"]["sorter"]).sort(owned, cfg["folders"]["name"])
        existing, raw, taken = await folders.read_existing(client)
        try:
            plans = folders.plan({k: [c.id for c in v] for k, v in groups.items()}, existing,
                                 config.folder_size(cfg), taken)
        except ValueError as e:
            raise SystemExit(str(e)) from None
        return owned, plans, raw

    out = await task(app, "Folders", "Planning your folders", make_plan)
    if await failed(app, "Folders", out):
        return
    owned, plans, raw = out.value
    lines = [f"{len(owned)} chats, {config.folder_size(cfg)} per folder.", ""]
    for p in plans:
        change = "no change" if p.action == "keep" else f"+{len(p.added)} −{len(p.removed)}"
        lines.append(f"{p.title}: {p.action} - {len(p.peer_ids)} chats ({change})")
    if all(p.action == "keep" for p in plans):
        await app.push_screen_wait(Result("Folders", "\n".join(lines + ["", "Already up to date."])))
        return
    lines.append("\nFolders not named like these are never touched.")
    pick = await app.push_screen_wait(Choice("Change these folders?", "\n".join(lines),
                                             [("yes", "Yes, change them"), ("no", "No")], default="no"))
    if pick != "yes":
        return

    async def apply(t):
        t.step("changing folders ...")
        return await folders.apply(client, plans, {c.id: c.input_peer for c in owned}, raw, limits.folders(cfg))

    out = await task(app, "Folders", "Changing your folders", apply)
    if await failed(app, "Folders", out):
        return
    problems = out.value
    text = "Done - the folders show in every Telegram app." if not problems else "\n".join(problems)
    await app.push_screen_wait(Result("Folders", text, ok=not problems))


# -- secure ------------------------------------------------------------------------


async def secure_flow(app, only: int | None = None) -> None:
    client = await ensure_client(app)
    cfg = app.cfg
    state = State()
    try:
        async def scan(t):
            t.step("finding your chats ...")
            owned = await chats.owned_chats(client, cfg["include_admin_chats"])
            picked = [c for c in owned if c.id == only] if only else owned

            def progress(result):
                files = sum(len(j.dep.files) for j in result.jobs)
                t.step(f"reading {len(picked)} chat(s): {result.messages} messages, {files} file(s) to keep")

            return await secure.scan(client, picked, {c.id for c in owned}, cfg, state, progress=progress,
                                     cancelled=t.cancelled)

        out = await task(app, "Make every file my own", "Reading your chats", scan)
        if await failed(app, "Make every file my own", out):
            return
        result = out.value
        notes = "\n".join(f"• {n}" for n in result.notes[:10])
        if len(result.notes) > 10:
            notes += f"\n• ... and {len(result.notes) - 10} more"
        if not result.jobs:
            await app.push_screen_wait(Result("Make every file my own",
                                              f"Read {result.messages} messages.\nNothing depends on anyone else - "
                                              f"every file is already your own.\n\n{notes}".strip()))
            return
        files = sum(len(j.dep.files) for j in result.jobs)
        size = sum(f.media.document.size if hasattr(f.media, "document") else 0
                   for j in result.jobs for f in j.dep.files)
        note = (f"{secure.describe(result)}\n\n"
                "Each file is downloaded and uploaded again as your own post; the forward "
                f"{'is deleted once its copy is checked' if cfg['secure']['replace'] else 'stays'} "
                "(Settings → Delete forwards). Ctrl+C stops after the current file; running it again goes on "
                f"where it stopped.\n\n{notes}").strip()
        pick = await app.push_screen_wait(Choice(f"{files} file(s), {human(size)} to keep", note,
                                                 [("go", f"Copy all {files} file(s) now"), ("no", "Not now")],
                                                 default="no"))
        if pick != "go":
            return

        async def copy(t):
            def report(n, total, job):
                t.step(f"copying {n} of {total}: {job.chat.title} #{job.own[0].id} - from {job.dep.source}")

            return await secure.run(client, result.jobs, cfg, state, report=report, cancelled=t.cancelled)

        out = await task(app, "Make every file my own", f"Copying {files} file(s)", copy)
        if await failed(app, "Make every file my own", out):
            return
        done, problems = out.value
        text = f"Kept {done} of {len(result.jobs)} as your own."
        if out.stopped:
            text += "\nStopped - run it again to go on where it stopped."
        if problems:
            text += "\n\n" + "\n".join(f"• {p}" for p in problems[:15]) + "\n\nRun it again to retry these."
        await app.push_screen_wait(Result("Make every file my own", text, ok=not problems))
    finally:
        state.close()


async def tidy_flow(app) -> None:
    title = "Delete forwards I have copies of"
    client = await ensure_client(app)
    cfg = app.cfg
    state = State()
    try:
        async def check(t):
            t.step("finding your chats ...")
            owned = await chats.owned_chats(client, cfg["include_admin_chats"])

            def progress(result):
                t.step(f"reading {len(owned)} chat(s): {result.messages} messages")

            # Records the copies made on another device too, so their forwards count.
            result = await secure.scan(client, owned, {c.id for c in owned}, cfg, state, progress=progress,
                                       cancelled=t.cancelled)
            if t.cancelled():
                return None
            plan, notes = await secure.tidy_plan(client, owned, state,
                                                 progress=lambda c: t.step(f"checking the copies in {c.title} ..."))
            waiting = sum(len(j.own) for j in result.jobs if j.dep.finder == "forwarded")
            return plan, notes, waiting

        out = await task(app, title, "Checking each forward against its copy", check)
        if await failed(app, title, out) or out.value is None:
            return
        plan, notes, waiting = out.value
        count = sum(len(t.forwards) for t in plan)
        later = (f"\n\n{waiting} forward(s) have no copy yet - Make every file my own copies them first; "
                 "they're not deleted." if waiting else "")
        listed = "\n".join(f"• {n}" for n in notes[:10])
        if len(notes) > 10:
            listed += f"\n• ... and {len(notes) - 10} more"
        if not count:
            await app.push_screen_wait(Result(title, f"No forward has a checked copy to delete.{later}\n\n{listed}"
                                              .strip()))
            return
        where = "\n".join(f"• {t.chat.title}: {len(t.forwards)}" for t in plan[:10])
        note = (f"{where}\n\nEach one's copy was read again just now: still in the chat, same file and caption. "
                f"Deleting can't be undone.{later}\n\n{listed}").strip()
        pick = await app.push_screen_wait(Choice(f"{count} forward(s) have their own copy", note,
                                                 [("go", f"Delete all {count} forward(s)"), ("no", "Not now")],
                                                 default="no"))
        if pick != "go":
            return

        async def delete(t):
            return await secure.tidy(client, plan, state, report=lambda n, total: t.step(f"deleted {n} of {total}"),
                                     cancelled=t.cancelled)

        out = await task(app, title, f"Deleting {count} forward(s)", delete)
        if await failed(app, title, out):
            return
        text = f"Deleted {out.value} of {count} forward(s). Their copies stay."
        if out.stopped:
            text += "\nStopped - run it again to delete the rest."
        await app.push_screen_wait(Result(title, text))
    finally:
        state.close()


# -- upload ------------------------------------------------------------------------


async def upload_flow(app, into=None) -> None:
    typed = await app.push_screen_wait(Ask("Upload a folder", "Type or paste the folder's path. Every file in it "
                                           "and in its sub-folders goes up; files over the limit go in parts.",
                                           placeholder="/home/you/Videos/My show"))
    if not typed:
        return
    root = Path(typed.strip().strip('"').strip("'")).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"{root} is not a folder.")
    client = await ensure_client(app)
    cfg = app.cfg
    state = State()
    try:
        owned = await chats.owned_chats(client, cfg["include_admin_chats"])
        entity = into.entity if into else None
        if into is None:
            last = state.target_for(str(root))
            pick = await app.push_screen_wait(Choice("Upload into", str(root), [
                ("auto", f'A private channel for it ("{root.name}" - the same one as last time, if any)'),
                ("me", "Saved Messages"),
                ("pick", "One of my channels or groups ...")]))
            if pick is None:
                return
            if pick == "me":
                entity = await client.get_entity("me")
            elif pick == "pick":
                from keepgram.ui.screens import PickChat

                chosen = await app.push_screen_wait(PickChat([HOME, "Upload a folder", "Into"], owned))
                if chosen is None:
                    return
                entity = chosen.entity
            elif last is not None:
                try:
                    entity = await client.get_entity(last)
                except (ValueError, TypeError, errors.RPCError):
                    entity = None

        async def check(t):
            t.step("listing the files ...")
            plan = await asyncio.to_thread(upload.walk, root, cfg["upload"].get("skip_hidden", True))
            if not plan.items:
                raise SystemExit("No files to upload in that folder.")
            size = upload.part_size(cfg)
            for n, item in enumerate(plan.items, 1):
                if t.cancelled():
                    raise SystemExit("Stopped.")
                t.step(f"checking {n} of {len(plan.items)}: {item.rel}")
                item.sha256 = await asyncio.to_thread(upload.sha256_of, item, state)
                item.pieces = upload.cut(Path(item.rel).name, item.size, size)
            chat_id = utils.get_peer_id(entity) if entity is not None else 0
            t.step("looking at what is already in the chat ...")
            in_chat = await upload.files_in_chat(client, entity) if entity is not None else set()
            return plan, chat_id, upload.find_duplicates(plan, chat_id, state, in_chat)

        out = await task(app, "Upload a folder", f"Checking {root.name}", check)
        if await failed(app, "Upload a folder", out):
            return
        plan, chat_id, dups = out.value
        skip: set = set()
        if dups.how:
            listed = "\n".join(f"• {rel} ({why})" for rel, why in list(dups.how.items())[:12])
            if len(dups.how) > 12:
                listed += f"\n• ... and {len(dups.how) - 12} more"
            pick = await app.push_screen_wait(Choice(f"{len(dups.how)} file(s) are already there", listed, [
                ("skip", "Skip them - upload only what isn't there"),
                ("again", "Upload them again anyway"),
                ("cancel", "Cancel")]))
            if pick in (None, "cancel"):
                return
            if pick == "skip":
                skip = dups.pieces
        todo = [(i, p) for i in plan.items for p in i.pieces if (i.rel, p.part) not in skip]
        if not todo:
            await app.push_screen_wait(Result("Upload a folder", "Everything in that folder is already there."))
            return
        where = utils.get_display_name(entity) if entity is not None else f'a new private channel "{root.name}"'
        size = sum(p.length for _i, p in todo)
        note = f"{len(todo)} file(s)/part(s), {human(size)}, into {where}."
        if plan.split:
            note += f"\n{len(plan.split)} file(s) over {human(upload.part_size(cfg))} go up in parts."
        pick = await app.push_screen_wait(Choice("Upload now?", note, [("go", "Upload"), ("no", "Not now")],
                                                 default="no"))
        if pick != "go":
            return

        async def send(t):
            nonlocal entity, chat_id
            if entity is None:
                t.step(f'making the private channel "{root.name}" ...')
                entity = await upload.create_channel(client, root.name)
                chat_id = utils.get_peer_id(entity)
            state.set_target(str(root), chat_id)
            t.step(f"uploading {len(todo)} file(s)/part(s) into {utils.get_display_name(entity)}")
            return await upload.send(client, entity, chat_id, plan, skip, cfg, state, cancelled=t.cancelled)

        out = await task(app, "Upload a folder", f"Uploading {root.name}", send)
        if await failed(app, "Upload a folder", out):
            return
        done, problems = out.value
        text = f"Uploaded {done} of {len(todo)}."
        if out.stopped:
            text += "\nStopped - upload the same folder again to go on; what's there is skipped."
        if problems:
            text += "\n\n" + "\n".join(f"• {p}" for p in problems[:15])
        await app.push_screen_wait(Result("Upload a folder", text, ok=not problems))
    finally:
        state.close()


# -- keep working in the background ------------------------------------------------


async def watch_flow(app) -> None:
    from keepgram import watch

    await ensure_client(app)  # logged in: the watcher copies this login
    about = ("While it runs, keepgram puts chats you make into the Keepgram folders (a new folder when one is "
             "full), takes out chats you leave, and copies new forwards in your chats as your own about a minute "
             "after they're posted. It never starts on your old files by itself - that is Make every file my own."
             "\n\nIt runs in this window: Ctrl+C - or closing the window - stops it.")
    while True:
        if watch.watching_elsewhere():
            options = [("log", "What it did lately"), ("back", "Back")]
            note = "keepgram is already watching in another window.\n\n" + about
        else:
            options = [("here", "Start watching"), ("log", "What it did lately"), ("back", "Back")]
            note = about
        pick = await app.push_screen_wait(Choice("Keep working while I use Telegram", note, options))
        if pick in (None, "back"):
            _home_info(app)
            return
        if pick == "log":
            await app.push_screen_wait(Result("What it did lately", watch.recent(40)))
        elif pick == "here":
            await _watch_here(app, watch)


async def _watch_here(app, watch) -> None:
    import logging

    async def run(t):
        class ToTask(logging.Handler):
            def emit(self, record):
                t.log(record.getMessage())

        handler = ToTask()
        watch.log.addHandler(handler)
        app.watching = True
        t.step("watching - Ctrl+C stops it")
        job = asyncio.ensure_future(watch.watch(app.cfg, to_console=False))
        try:
            while not t.cancelled() and not job.done():
                await asyncio.sleep(0.5)
            if job.done():
                job.result()  # its error, if it ended by itself
        finally:
            job.cancel()
            # Wait for it to really end - disconnected, its lock let go - before the
            # menu asks "is anyone watching?" (it said "yes" right after Ctrl+C).
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await job
            watch.log.removeHandler(handler)
            app.watching = False
        return None

    out = await task(app, "Keep working", "keepgram is watching", run)
    if not out.ok and not out.stopped:
        await failed(app, "Keep working", out)


# -- join ----------------------------------------------------------------------------


async def join_flow(app) -> None:
    typed = await app.push_screen_wait(Ask("Join downloaded parts", "The .001 file, or a folder - every set of "
                                           "parts in it is joined.", placeholder="/home/you/Downloads/movie.mkv.001"))
    if not typed:
        return
    target = Path(typed.strip().strip('"').strip("'")).expanduser()
    firsts = join.firsts_in(target) if target.is_dir() else [target]
    if not firsts:
        raise SystemExit(f"No .001 parts in {target}.")

    async def work(t):
        lines = []
        for n, first in enumerate(firsts, 1):
            t.step(f"joining {n} of {len(firsts)}: {first.name}")
            out, digest = await asyncio.to_thread(join.join, first)
            lines.append(f"{out}\nsha256 {digest}")
        return lines

    out = await task(app, "Join parts", "Joining parts", work)
    if await failed(app, "Join parts", out):
        return
    await app.push_screen_wait(Result("Join parts", "\n\n".join(out.value) + "\n\nCompare each sha256 with the line "
                                      "under the parts on Telegram - the same means the file is whole."))


# -- bot -----------------------------------------------------------------------------


async def bot_flow(app) -> None:
    cfg = app.cfg
    if not cfg["bot"].get("token"):
        token = await app.push_screen_wait(Ask(
            "Bot token", "Make a bot: talk to @BotFather in Telegram, send /newbot, and paste the token it gives "
            "you. It is saved in config.json.", password=True))
        if not token:
            return
        cfg["bot"]["token"] = token.strip()
        config.save(cfg)
    if not cfg.get("api_id"):
        await ensure_client(app)

    async def run(t):
        t.step("starting the bot ...")
        client, bot, store = await botmod.start(cfg)
        try:
            t.step(f"running as @{bot.me.username} in {store.chat_count()} chat(s) - Ctrl+C stops it")
            t.log(f"Share this link: https://t.me/{bot.me.username}")
            t.log("The bot works only while this screen is open.")
            while not t.cancelled() and client.is_connected():
                await asyncio.sleep(0.5)
        finally:
            await client.disconnect()
            store.close()
        return bot.me.username

    out = await task(app, "Bot", "The keepgram bot", run)
    if out.ok:
        await app.push_screen_wait(Result("Bot", f"@{out.value} stopped."))
    else:
        await failed(app, "Bot", out)
