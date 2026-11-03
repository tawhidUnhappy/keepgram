"""keepgram's plug-ins: anything that comes in more than one flavour is a
plug-in, registered under its kind - nothing else names a particular one.

    kind     what one is                                          built in
    finder   spots a message whose file depends on someone else   forwarded, post_link
    sorter   splits your chats into folder series                 one_series, by_type

Each built-in is a module here. Your own is a .py file or package in the
top-level plugins/ folder, or an installed package with a `keepgram.plugins`
entry point - see plugins/README.md. A plug-in with the same kind and name as
a built-in replaces it."""

from __future__ import annotations

from keepgram.plugins._kinds import Context, Dependency, Finder, Sorter
from keepgram.plugins._loader import failures, load
from keepgram.plugins._registry import KINDS, get, items, origin, register

__all__ = [
    "KINDS",
    "Context",
    "Dependency",
    "Finder",
    "Sorter",
    "failures",
    "get",
    "items",
    "load",
    "origin",
    "register",
]
