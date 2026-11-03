"""t.me links to single posts - the kind that stop working the moment the post,
the channel or its owner's account is gone."""

from __future__ import annotations

import re
from dataclasses import dataclass

# t.me/name/123, t.me/name/<topic>/123, t.me/s/name/123, t.me/c/<id>/123,
# t.me/c/<id>/<topic>/123 (telegram.me and telegram.dog too).
_POST = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/(?:s/)?"
    r"(?:c/(?P<cid>\d+)|(?P<user>[A-Za-z][A-Za-z0-9_]{3,31}))"
    r"/(?:\d+/)?(?P<msg>\d+)(?![\d/])"
)
# Paths on t.me that are not channel usernames.
_RESERVED = {"joinchat", "addstickers", "addemoji", "addlist", "share", "proxy", "socks", "boost", "iv", "login"}


@dataclass(frozen=True)
class PostLink:
    url: str
    username: str | None  # public chats
    chat_id: int | None  # private chats, as Telethon's marked id (-100...)
    msg_id: int

    @property
    def peer(self) -> str | int:
        return self.username if self.username else self.chat_id


def find(text: str) -> list[PostLink]:
    out: list[PostLink] = []
    for m in _POST.finditer(text or ""):
        user = m.group("user")
        if user and user.lower() in _RESERVED:
            continue
        cid = int("-100" + m.group("cid")) if m.group("cid") else None
        link = PostLink(m.group(0), user, cid, int(m.group("msg")))
        if link not in out:
            out.append(link)
    return out


def in_message(msg) -> list[PostLink]:
    """Links in a message's text and behind its text links ([word](url))."""
    text = msg.message or ""
    hidden = " ".join(getattr(e, "url", "") or "" for e in (msg.entities or []))
    return find(text + " " + hidden)


def without_links(text: str) -> str:
    """The text with every post link taken out - blank means the message was
    nothing but links."""
    return _POST.sub("", text or "").strip()
