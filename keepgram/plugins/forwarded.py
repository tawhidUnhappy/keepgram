"""finder `forwarded`: a file forwarded into your chat from someone else.

Telegram keeps a forward when the original is deleted, but the forward still
carries the other chat's name and points at the same stored file - a file
Telegram takes down there can go here too. Your own upload has neither tie."""

from __future__ import annotations

from telethon import utils

from keepgram.media import has_file
from keepgram.plugins import Context, Dependency, Finder, register


async def find(ctx: Context, msg) -> Dependency | None:
    fwd = msg.fwd_from
    if fwd is None or not has_file(msg):
        return None
    origin = fwd.from_id or fwd.saved_from_peer
    peer_id = utils.get_peer_id(origin) if origin is not None else None
    if peer_id == ctx.me_id:
        return None
    if peer_id in ctx.owned_ids and ctx.cfg["secure"].get("skip_own_sources", True):
        return None
    source = fwd.from_name or fwd.post_author or await ctx.name(peer_id)
    return Dependency("forwarded", source, [msg], replaceable=True)


register("finder", Finder("forwarded", "Forwards", "files forwarded from other people's chats", find, order=10))
