"""keepgram's commands. ./run.sh with no command opens a numbered menu."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

from telethon import utils

from keepgram import __version__, chats, config, folders, join, limits, paths, plugins, secure, telegram, upload
from keepgram.media import human
from keepgram.state import State


def confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


# -- login ---------------------------------------------------------------------


async def cmd_login(args, cfg):
    if not cfg.get("api_id") or not cfg.get("api_hash"):
        print("keepgram logs in as you, through an API app of your own:")
        print("  1. open https://my.telegram.org and log in")
        print("  2. API development tools -> create an app (any name)")
        print("  3. copy its api_id and api_hash here - they are saved in", paths.CONFIG)
        cfg["api_id"] = int(input("api_id: ").strip())
        cfg["api_hash"] = getpass.getpass("api_hash (hidden): ").strip()
        config.save(cfg)
    client = await telegram.login(cfg)
    me = await client.get_me()
    print(f"Logged in as {me.first_name} (@{me.username or '-'}). The login is in {paths.SESSION} -"
          " it opens your account, never share it.")
    await client.disconnect()


# -- chats / folders -----------------------------------------------------------------


async def cmd_chats(args, cfg):
    client = await telegram.connect(cfg)
    try:
        owned = await chats.owned_chats(client, cfg["include_admin_chats"])
    finally:
        await client.disconnect()
    for c in owned:
        role = "creator" if c.creator else "admin"
        print(f"  {c.kind:7}  {role:7}  {c.id:>16}  {c.title}")
    print(f"{len(owned)} chat(s): {sum(c.kind == 'channel' for c in owned)} channels, "
          f"{sum(c.kind == 'group' for c in owned)} groups")


async def cmd_folders(args, cfg):
    plugins.load()
    client = await telegram.connect(cfg)
    try:
        owned = await chats.owned_chats(client, cfg["include_admin_chats"])
        sorter = plugins.get("sorter", cfg["folders"]["sorter"])
        groups = sorter.sort(owned, cfg["folders"]["name"])
        ids = {name: [c.id for c in members] for name, members in groups.items()}
        existing, raw, taken = await folders.read_existing(client)
        try:
            plans = folders.plan(ids, existing, config.folder_size(cfg), taken)
        except ValueError as e:
            raise SystemExit(str(e)) from None
        print(f"{len(owned)} chat(s), {config.folder_size(cfg)} per folder:")
        for p in plans:
            change = f"+{len(p.added)} -{len(p.removed)}" if p.action != "keep" else "no change"
            print(f"  {p.title:12}  {p.action:6}  {len(p.peer_ids):3} chats  ({change})")
        if all(p.action == "keep" for p in plans):
            print("Folders are already up to date.")
            return
        if args.dry_run or not confirm("Change these folders?", args.yes):
            return
        problems = await folders.apply(client, plans, {c.id: c.input_peer for c in owned}, raw,
                                       limits.folders(cfg))
    finally:
        await client.disconnect()
    for line in problems:
        print("  problem:", line)
    print("Folders done." if not problems else f"Folders done, {len(problems)} problem(s) above.")


# -- secure --------------------------------------------------------------------


async def cmd_secure(args, cfg):
    if args.replace:
        cfg["secure"]["replace"] = True
    state = State()
    client = await telegram.connect(cfg)
    try:
        owned = await chats.owned_chats(client, cfg["include_admin_chats"])
        picked = chats.pick(owned, args.chat) if args.chat else owned
        if not picked:
            raise SystemExit(f"none of your chats matches {args.chat!r} - see: chats")
        result = await secure.scan(client, picked, {c.id for c in owned}, cfg, state)
        print(f"Read {result.messages} message(s) in {len(picked)} chat(s).")
        for note in result.notes:
            print("  note:", note)
        if not result.jobs:
            print("Nothing depends on anyone else - every file is already your own.")
            return
        print(secure.describe(result))
        if cfg["secure"].get("replace"):
            print("  replace is on: each forward (or bare link) is deleted after its copy is posted and checked")
        if args.dry_run or not confirm("Copy them now?", args.yes):
            return
        done, problems = await secure.run(client, result.jobs, cfg, state)
    finally:
        await client.disconnect()
        state.close()
    print(f"Kept {done} of {len(result.jobs)}.")
    for line in problems:
        print("  problem:", line)
    if problems:
        print("Run secure again to retry the ones that failed.")


async def cmd_tidy(args, cfg):
    state = State()
    client = await telegram.connect(cfg)
    try:
        owned = await chats.owned_chats(client, cfg["include_admin_chats"])
        picked = chats.pick(owned, args.chat) if args.chat else owned
        if not picked:
            raise SystemExit(f"none of your chats matches {args.chat!r} - see: chats")
        result = await secure.scan(client, picked, {c.id for c in owned}, cfg, state)
        plan, notes = await secure.tidy_plan(client, picked, state)
        for note in notes:
            print("  note:", note)
        waiting = sum(len(j.own) for j in result.jobs if j.dep.finder == "forwarded")
        if waiting:
            print(f"{waiting} forward(s) have no copy yet - run secure first; they're not deleted.")
        count = sum(len(t.forwards) for t in plan)
        if not count:
            print("No forward has a checked copy to delete.")
            return
        for t in plan:
            print(f"  {t.chat.title}: {len(t.forwards)} forward(s)")
        if args.dry_run or not confirm(f"Delete {count} forward(s)? Their copies stay.", args.yes):
            return
        done = await secure.tidy(client, plan, state)
    finally:
        await client.disconnect()
        state.close()
    print(f"Deleted {done} of {count} forward(s).")


# -- upload --------------------------------------------------------------------


def _ask_duplicates(count: int, mode: str, yes: bool) -> str:
    if mode != "ask":
        return mode
    if yes:
        return "skip"
    print(f"{count} file(s) are already in that chat. What should happen to them?")
    print("  s  skip them - upload only what isn't there (default)")
    print("  a  upload them again anyway")
    print("  c  cancel")
    while True:
        try:
            answer = input("[s/a/c] ").strip().lower() or "s"
        except EOFError:
            answer = "c"
        if answer in ("s", "skip"):
            return "skip"
        if answer in ("a", "again", "all"):
            return "again"
        if answer in ("c", "cancel"):
            return "cancel"


async def cmd_upload(args, cfg):
    root = Path(args.folder).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"{root} is not a folder")
    plan = upload.walk(root, cfg["upload"].get("skip_hidden", True))
    for note in plan.skipped:
        print("  skipped:", note)
    if not plan.items:
        raise SystemExit("No files to upload in that folder.")
    state = State()
    client = await telegram.connect(cfg)
    try:
        owned = await chats.owned_chats(client, cfg["include_admin_chats"])  # also loads every chat you're in
        entity = None
        if args.to:
            entity = await upload.resolve_target(client, args.to, owned)
        elif (saved := state.target_for(str(root))) is not None:
            try:
                entity = await client.get_entity(saved)
            except (ValueError, TypeError):
                entity = None  # that channel is gone - a new one is made
        size = upload.part_size(cfg)
        for item in plan.items:
            item.sha256 = upload.sha256_of(item, state)
            item.pieces = upload.cut(Path(item.rel).name, item.size, size)
        chat_id = utils.get_peer_id(entity) if entity is not None else 0
        in_chat = await upload.files_in_chat(client, entity) if entity is not None else set()
        dups = upload.find_duplicates(plan, chat_id, state, in_chat)

        where = utils.get_display_name(entity) if entity is not None else f'a new private channel "{root.name}"'
        print(f"{len(plan.items)} file(s), {human(plan.size)}, into {where}")
        if plan.split:
            parts = sum(len(i.pieces) for i in plan.split)
            print(f"  {len(plan.split)} file(s) over {human(size)} go up as {parts} parts")
        skip: set = set()
        if dups.how:
            for rel, why in list(dups.how.items())[:10]:
                print(f"  already there: {rel} ({why})")
            if len(dups.how) > 10:
                print(f"  ... and {len(dups.how) - 10} more")
            mode = _ask_duplicates(len(dups.how), args.duplicates, args.yes)
            if mode == "cancel":
                return
            if mode == "skip":
                skip = dups.pieces
        left = sum(1 for i in plan.items for p in i.pieces if (i.rel, p.part) not in skip)
        if not left:
            print("Everything in that folder is already there.")
            return
        if args.dry_run or not confirm(f"Upload {left} file(s)/part(s) now?", args.yes):
            return
        if entity is None:
            entity = await upload.create_channel(client, root.name)
            chat_id = utils.get_peer_id(entity)
            print(f'Made the private channel "{entity.title}".')
        state.set_target(str(root), chat_id)
        done, problems = await upload.send(client, entity, chat_id, plan, skip, cfg, state)
    finally:
        await client.disconnect()
        state.close()
    print(f"Uploaded {done} of {left}.")
    for line in problems:
        print("  problem:", line)
    if problems:
        print("Run the same upload again to send what failed - the rest is skipped.")


# -- join / status / plugins ---------------------------------------------------


def cmd_join(args, cfg):
    target = Path(args.path).expanduser()
    firsts = join.firsts_in(target) if target.is_dir() else [target]
    if not firsts:
        raise SystemExit(f"no .001 parts in {target}")
    for first in firsts:
        out, digest = join.join(first)
        print(f"  {out}\n  sha256 {digest} - compare it with the line under the parts on Telegram")


def cmd_status(args, cfg):
    print(f"keepgram {__version__}, home {paths.HOME}")
    print(f"  logged in: {'yes' if paths.SESSION.is_file() else 'no - run: login'}")
    lim = limits.cached()
    learned = "learned from Telegram" if lim.get("learned_at") else "Telegram's defaults (not learned yet)"
    print(f"  premium: {'yes' if limits.premium(cfg) else 'no'} - files up to {human(config.file_limit(cfg))}, "
          f"{config.folder_size(cfg)} chats per folder, {limits.folders(cfg)} folders ({learned})")
    if paths.STATE.is_file():
        state = State()
        print(f"  files kept as your own: {state.kept_count()}")
        print(f"  files/parts uploaded:   {state.uploaded_count()}")
        state.close()


def cmd_plugins(args, cfg):
    plugins.load()
    for kind in plugins.KINDS:
        print(f"{kind}:")
        for p in plugins.items(kind):
            print(f"  {p.name:12} {p.description}  [{plugins.origin(kind, p.name)}]")
    for where, error in plugins.failures():
        print(f"failed: {where}\n{error}")


# -- wiring --------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="keepgram", description="Keep your Telegram files your own.")
    ap.add_argument("--version", action="version", version=f"keepgram {__version__}")
    sub = ap.add_subparsers(dest="command")

    sub.add_parser("login", help="log in to your Telegram account (once)")
    sub.add_parser("chats", help="list the channels and groups you own")

    p = sub.add_parser("folders", help='sort your chats into folders "Keepgram 1", "Keepgram 2", ...')
    p.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask before changing")

    p = sub.add_parser("secure", help="re-upload files that depend on someone else's post as your own")
    p.add_argument("--chat", help="only this chat (id or title)")
    p.add_argument("--replace", action="store_true", help="delete each forward once its copy is safe")
    p.add_argument("--dry-run", action="store_true", help="show what would be copied, change nothing")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask before copying")

    p = sub.add_parser("tidy", help="delete the forwards whose own copy is in the chat (checked first)")
    p.add_argument("--chat", help="only this chat (id or title)")
    p.add_argument("--dry-run", action="store_true", help="show what would be deleted, change nothing")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask before deleting")

    p = sub.add_parser("all", help="folders, then secure")
    p.add_argument("--replace", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-y", "--yes", action="store_true")

    p = sub.add_parser("upload", help="upload a folder from disk - every file, big ones in parts")
    p.add_argument("folder")
    p.add_argument("--to", help="me (Saved Messages), @username, a chat id or one of your chats' titles;"
                                " default: a new private channel named after the folder (the same one next time)")
    p.add_argument("--duplicates", choices=("ask", "skip", "again"), default="ask",
                   help="files already in the chat: ask (default), skip them, or upload again")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-y", "--yes", action="store_true")

    p = sub.add_parser("join", help="join name.ext.001, .002, ... back into the file")
    p.add_argument("path", help="the .001 file, or a folder to join every set in")

    p = sub.add_parser("watch", help="keep working while you use Telegram (until you close the window)")
    p.add_argument("--log", action="store_true", help="is it watching in some window, and what it did lately")

    sub.add_parser("bot", help="run keepgram as a Telegram bot anyone can add to their channels and groups")
    sub.add_parser("status", help="login, limits and what has been done")
    sub.add_parser("plugins", help="list the finder and sorter plug-ins")
    return ap


async def cmd_watch(args, cfg):
    from keepgram import watch

    if args.log:
        print("watching in a window now:", "yes" if watch.watching_elsewhere() else "no")
        print(watch.recent(20))
        return
    print("keepgram is watching - close this window or press Ctrl+C to stop it.")
    try:
        await watch.watch(cfg, to_console=True)
    except SystemExit as e:
        watch.log.error("stopped: %s", e.code)
        raise


async def cmd_bot(args, cfg):
    from keepgram import bot

    await bot.serve(cfg)


async def cmd_all(args, cfg):
    await cmd_folders(args, cfg)
    args.chat = None
    await cmd_secure(args, cfg)


ASYNC = {"login": cmd_login, "chats": cmd_chats, "folders": cmd_folders, "secure": cmd_secure, "tidy": cmd_tidy,
         "all": cmd_all, "upload": cmd_upload, "bot": cmd_bot, "watch": cmd_watch}
SYNC = {"join": cmd_join, "status": cmd_status, "plugins": cmd_plugins}

def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from keepgram import ui

        ui.run()
        return
    args = parser().parse_args(argv)
    if not args.command:
        parser().print_help()
        return
    cfg = config.load()
    try:
        if args.command in SYNC:
            SYNC[args.command](args, cfg)
        else:
            asyncio.run(ASYNC[args.command](args, cfg))
    except KeyboardInterrupt:
        print("\nStopped. Run it again to continue where it was.")


if __name__ == "__main__":
    main()
