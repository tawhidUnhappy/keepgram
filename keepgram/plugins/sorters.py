"""sorters: which folder series each chat goes in."""

from __future__ import annotations

from keepgram.plugins import Sorter, register


def one_series(chats, base: str):
    """Everything in "<name> 1", "<name> 2", ..."""
    return {base: list(chats)}


def by_type(chats, base: str):
    """Channels and groups apart: "Channels 1", ..., "Groups 1", ..."""
    out = {"Channels": [c for c in chats if c.kind == "channel"], "Groups": [c for c in chats if c.kind == "group"]}
    return {name: members for name, members in out.items() if members}


register("sorter", Sorter("one_series", "One series", "every chat in <name> 1, <name> 2, ...", one_series, order=10))
register("sorter", Sorter("by_type", "By type", "Channels 1, 2, ... and Groups 1, 2, ...", by_type, order=20))
