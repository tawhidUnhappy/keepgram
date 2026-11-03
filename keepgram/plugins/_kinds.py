"""What each kind of plug-in describes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Dependency:
    """A message in your chat whose file isn't really yours yet."""

    finder: str
    source: str  # where it depends on, for people: "@somechannel", "Deleted Account", a link
    files: list[Any]  # the messages holding the files to copy (Telethon Messages)
    # The message in your chat may go once your copy is safe (secure.replace):
    # true for a forward, true for a message that is nothing but links.
    replaceable: bool
    # Things the finder saw but couldn't (or mustn't) copy - shown in the report.
    notes: list[str] = field(default_factory=list)


@dataclass
class Context:
    """What a finder gets besides the message."""

    client: Any
    me_id: int
    owned_ids: set[int]
    cfg: dict
    _names: dict[int, str] = field(default_factory=dict)
    _entities: dict[Any, Any] = field(default_factory=dict)

    async def name(self, peer_id: int | None) -> str:
        if peer_id is None:
            return "a hidden account"
        if peer_id not in self._names:
            try:
                ent = await self.client.get_entity(peer_id)
                user = getattr(ent, "username", None)
                title = getattr(ent, "title", None) or " ".join(
                    x for x in (getattr(ent, "first_name", None), getattr(ent, "last_name", None)) if x
                )
                self._names[peer_id] = f"@{user}" if user else (title or "Deleted Account")
            except (ValueError, TypeError):
                self._names[peer_id] = "an unknown chat"
            except Exception as e:  # an RPC error: the chat is gone or private
                self._names[peer_id] = f"an unreachable chat ({type(e).__name__})"
        return self._names[peer_id]

    async def entity(self, peer):
        """get_entity, once per run - resolving usernames is rate limited hard."""
        if peer not in self._entities:
            self._entities[peer] = await self.client.get_entity(peer)
        return self._entities[peer]


@dataclass
class Finder:
    name: str
    label: str
    description: str
    # find(ctx, message) -> Dependency | None
    find: Callable[[Context, Any], Awaitable[Dependency | None]]
    order: int = 100


@dataclass
class Sorter:
    name: str
    label: str
    description: str
    # sort(chats, base_name) -> {folder series name: [OwnedChat, ...]}
    sort: Callable[[list, str], dict[str, list]]
    order: int = 100
