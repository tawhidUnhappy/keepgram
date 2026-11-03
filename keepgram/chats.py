"""Your own channels and groups: the ones you created (and, if you ask, the
ones you are an admin of)."""

from __future__ import annotations

from dataclasses import dataclass

from telethon import utils
from telethon.tl import types


@dataclass
class OwnedChat:
    id: int  # Telethon's marked id: -100... for channels/supergroups, -... for basic groups
    title: str
    kind: str  # "channel" or "group"
    creator: bool
    entity: object  # the Channel / Chat, for building requests

    @property
    def input_peer(self):
        return utils.get_input_peer(self.entity)


def _owned(entity, include_admin: bool) -> OwnedChat | None:
    if isinstance(entity, types.Channel):
        if entity.left:
            return None
        kind = "group" if (entity.megagroup or entity.gigagroup) else "channel"
    elif isinstance(entity, types.Chat):
        # A basic group that became a supergroup lives on as the Channel.
        if entity.left or entity.deactivated or entity.migrated_to:
            return None
        kind = "group"
    else:
        return None
    is_admin = entity.admin_rights is not None
    if not entity.creator and not (include_admin and is_admin):
        return None
    return OwnedChat(utils.get_peer_id(entity), entity.title, kind, bool(entity.creator), entity)


async def owned_chats(client, include_admin: bool = False) -> list[OwnedChat]:
    """Every dialog, archived ones included; also fills Telethon's cache with
    every chat you are in, which link lookups later rely on."""
    out: list[OwnedChat] = []
    async for dialog in client.iter_dialogs():
        chat = _owned(dialog.entity, include_admin)
        if chat:
            out.append(chat)
    out.sort(key=lambda c: c.title.casefold())
    return out


def pick(chats: list[OwnedChat], wanted: str) -> list[OwnedChat]:
    """--chat: an id, or a title (exact first, then a part of one)."""
    wanted = wanted.strip()
    if wanted.lstrip("-").isdigit():
        n = int(wanted)
        return [c for c in chats if c.id == n or abs(c.id) == n or c.id == int(f"-100{abs(n)}")]
    exact = [c for c in chats if c.title.casefold() == wanted.casefold()]
    return exact or [c for c in chats if wanted.casefold() in c.title.casefold()]
