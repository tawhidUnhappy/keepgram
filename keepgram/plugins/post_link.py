"""finder `post_link`: a t.me link to a post with a file - the link dies with
the post, so the file is fetched and posted here as your own.

Posts in chats whose owner turned on "Restrict saving content" are left alone
and listed in the report: that choice is theirs."""

from __future__ import annotations

from telethon import errors, utils

from keepgram import links
from keepgram.media import has_file
from keepgram.plugins import Context, Dependency, Finder, register


async def _album(ctx: Context, entity, first) -> list:
    if not first.grouped_id:
        return [first]
    around = await ctx.client.get_messages(entity, ids=list(range(first.id - 9, first.id + 10)))
    return [m for m in around if m is not None and m.grouped_id == first.grouped_id and has_file(m)]


async def find(ctx: Context, msg) -> Dependency | None:
    found = links.in_message(msg)
    if not found:
        return None
    files, sources, notes = [], [], []
    for link in found:
        try:
            entity = await ctx.entity(link.peer)
        except (ValueError, TypeError, errors.RPCError):
            notes.append(f"{link.url}: the chat is gone or you are not in it")
            continue
        peer_id = utils.get_peer_id(entity)
        if peer_id in ctx.owned_ids and ctx.cfg["secure"].get("skip_own_sources", True):
            continue
        if getattr(entity, "noforwards", False):
            notes.append(f"{link.url}: its owner restricted saving - not copied")
            continue
        try:
            post = await ctx.client.get_messages(entity, ids=link.msg_id)
        except errors.RPCError as e:
            notes.append(f"{link.url}: {e}")
            continue
        if post is None:
            notes.append(f"{link.url}: the post is already gone")
            continue
        if getattr(post, "noforwards", False):
            notes.append(f"{link.url}: its owner restricted saving - not copied")
            continue
        if not has_file(post):
            continue
        for m in await _album(ctx, entity, post):
            if all(not (m.id == f.id and m.chat_id == f.chat_id) for f in files):
                files.append(m)
        sources.append(link.url)
    if not files:
        return Dependency("post_link", "", [], replaceable=False, notes=notes) if notes else None
    only_links = not links.without_links(msg.message) and not has_file(msg)
    return Dependency("post_link", ", ".join(sources), files, replaceable=only_links, notes=notes)


register("finder", Finder("post_link", "Post links", "t.me links to posts with files", find, order=20))
