"""What the bot remembers, on top of State's records of kept files: the chats
it was added to, their switches, and who may manage each one."""

from __future__ import annotations

import time
from dataclasses import dataclass

from keepgram.state import State

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_chats (
    chat_id   INTEGER PRIMARY KEY,
    title     TEXT NOT NULL,
    kind      TEXT NOT NULL,              -- channel | group
    auto      INTEGER NOT NULL DEFAULT 1, -- keep new forwards as they arrive
    replace   INTEGER NOT NULL DEFAULT 0, -- delete the forward after copying
    top_id    INTEGER NOT NULL DEFAULT 0, -- newest message number seen
    added_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_managers (
    chat_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);
"""


@dataclass
class BotChat:
    chat_id: int
    title: str
    kind: str
    auto: bool
    replace: bool
    top_id: int


class BotStore(State):
    def __init__(self, path):
        super().__init__(path)
        self.db.executescript(_SCHEMA)

    def add_chat(self, chat_id: int, title: str, kind: str, manager: int | None) -> bool:
        """True if the chat is new to the bot."""
        new = self.chat(chat_id) is None
        with self.db:
            if new:
                self.db.execute("INSERT INTO bot_chats (chat_id, title, kind, added_at) VALUES (?,?,?,?)",
                                (chat_id, title, kind, time.time()))
            else:
                self.db.execute("UPDATE bot_chats SET title=? WHERE chat_id=?", (title, chat_id))
        if manager:
            self.add_manager(chat_id, manager)
        return new

    def remove_chat(self, chat_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM bot_chats WHERE chat_id=?", (chat_id,))
            self.db.execute("DELETE FROM bot_managers WHERE chat_id=?", (chat_id,))

    def chat(self, chat_id: int) -> BotChat | None:
        row = self.db.execute("SELECT chat_id, title, kind, auto, replace, top_id FROM bot_chats WHERE chat_id=?",
                              (chat_id,)).fetchone()
        return BotChat(row[0], row[1], row[2], bool(row[3]), bool(row[4]), row[5]) if row else None

    def add_manager(self, chat_id: int, user_id: int) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO bot_managers VALUES (?,?)", (chat_id, user_id))

    def chats_of(self, user_id: int) -> list[BotChat]:
        ids = [r[0] for r in self.db.execute("SELECT chat_id FROM bot_managers WHERE user_id=?", (user_id,))]
        chats = [c for c in map(self.chat, ids) if c]
        return sorted(chats, key=lambda c: c.title.casefold())

    def managed_together(self, chat_id: int) -> set[int]:
        """Every chat sharing a manager with this one: forwards between them
        aren't from someone else."""
        rows = self.db.execute(
            "SELECT DISTINCT b.chat_id FROM bot_managers a JOIN bot_managers b ON a.user_id=b.user_id "
            "WHERE a.chat_id=?", (chat_id,))
        return {r[0] for r in rows} | {chat_id}

    def set_flag(self, chat_id: int, name: str, value: bool) -> None:
        if name not in ("auto", "replace"):
            raise ValueError(name)
        with self.db:
            self.db.execute(f"UPDATE bot_chats SET {name}=? WHERE chat_id=?", (int(value), chat_id))

    def bump_top(self, chat_id: int, msg_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE bot_chats SET top_id=MAX(top_id, ?) WHERE chat_id=?", (msg_id, chat_id))

    def kept_in(self, chat_id: int) -> int:
        return self.db.execute("SELECT COUNT(*) FROM kept WHERE chat_id=? AND msg_id>0", (chat_id,)).fetchone()[0]

    def chat_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM bot_chats").fetchone()[0]
