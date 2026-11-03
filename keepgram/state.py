"""What keepgram has already done, in data/state.db, so every command can be
run again and picks up where it stopped - nothing is copied or uploaded twice
unless you ask for it."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from keepgram import paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kept (
    chat_id     INTEGER NOT NULL,
    msg_id      INTEGER NOT NULL,   -- the message in your chat that depended on someone else
    new_msg_id  INTEGER NOT NULL,   -- your own copy
    finder      TEXT NOT NULL,
    source      TEXT NOT NULL,
    removed     INTEGER NOT NULL DEFAULT 0,  -- the original was deleted afterwards (replace)
    at          REAL NOT NULL,
    PRIMARY KEY (chat_id, msg_id)
);
CREATE INDEX IF NOT EXISTS kept_copies ON kept (chat_id, new_msg_id);
CREATE TABLE IF NOT EXISTS uploaded (
    chat_id     INTEGER NOT NULL,
    sha256      TEXT NOT NULL,      -- of the whole file, so a renamed or moved file is still the same file
    part        INTEGER NOT NULL,   -- 1-based; 1 of 1 for a file sent whole
    parts       INTEGER NOT NULL,
    rel_path    TEXT NOT NULL,
    size        INTEGER NOT NULL,
    msg_id      INTEGER NOT NULL,
    at          REAL NOT NULL,
    PRIMARY KEY (chat_id, sha256, part, parts)
);
CREATE TABLE IF NOT EXISTS upload_targets (
    root        TEXT PRIMARY KEY,   -- the folder on disk
    chat_id     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    chat_id     INTEGER NOT NULL,   -- a copy in progress: another keepgram (the watcher,
    msg_id      INTEGER NOT NULL,   -- the menus) leaves this message alone meanwhile
    pid         INTEGER NOT NULL,
    at          REAL NOT NULL,
    PRIMARY KEY (chat_id, msg_id)
);
CREATE TABLE IF NOT EXISTS posting (
    chat_id     INTEGER NOT NULL,   -- a copy about to be posted: if this row outlives the run
    msg_id      INTEGER NOT NULL,   -- (power cut, window closed), the next run looks for that
    started     REAL NOT NULL,      -- copy before posting another
    PRIMARY KEY (chat_id, msg_id)
);
CREATE TABLE IF NOT EXISTS watch_marks (
    chat_id     INTEGER PRIMARY KEY,
    last_id     INTEGER NOT NULL    -- the watcher has looked at everything up to here
);
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hashes (
    path        TEXT PRIMARY KEY,
    size        INTEGER NOT NULL,
    mtime_ns    INTEGER NOT NULL,
    sha256      TEXT NOT NULL
);
"""


def _alive(pid: int) -> bool:
    """Is that process still running? Only asked where it's safe to ask
    (os.kill(pid, 0) on Windows would end it) - there, old claims just expire."""
    if os.name == "nt":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class State:
    def __init__(self, path: Path | None = None):
        path = path or paths.STATE
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread off: the menus hash big files in a worker thread; access
        # is still one at a time.
        # timeout: the watcher and the menus may both write; wait for the other
        # instead of failing with "database is locked".
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.db.executescript(_SCHEMA)

    def close(self) -> None:
        self.db.close()

    # -- secure ------------------------------------------------------------
    def is_kept(self, chat_id: int, msg_id: int) -> bool:
        row = self.db.execute("SELECT 1 FROM kept WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)).fetchone()
        return row is not None

    def is_copy(self, chat_id: int, msg_id: int) -> bool:
        """One of keepgram's own copies - its caption may hold the very link it
        was made from, so it must never be read as a new find."""
        row = self.db.execute("SELECT 1 FROM kept WHERE chat_id=? AND new_msg_id=?", (chat_id, msg_id)).fetchone()
        return row is not None

    def mark_kept(self, chat_id: int, msg_id: int, new_msg_id: int, finder: str, source: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO kept (chat_id, msg_id, new_msg_id, finder, source, at) VALUES (?,?,?,?,?,?)",
                (chat_id, msg_id, new_msg_id, finder, source, time.time()),
            )

    def mark_removed(self, chat_id: int, msg_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE kept SET removed=1 WHERE chat_id=? AND msg_id=?", (chat_id, msg_id))

    def forget(self, chat_id: int, msg_id: int) -> None:
        """Its copy is gone: copy it again next time."""
        with self.db:
            self.db.execute("DELETE FROM kept WHERE chat_id=? AND msg_id=?", (chat_id, msg_id))

    def kept_forwards(self, chat_id: int) -> list[tuple[int, int]]:
        """(forward, its copy) for each copied forward that is still there."""
        return self.db.execute(
            "SELECT msg_id, new_msg_id FROM kept WHERE chat_id=? AND finder='forwarded' AND removed=0 AND msg_id>0 "
            "ORDER BY msg_id", (chat_id,)).fetchall()

    # -- claims (one copy at a time, across processes) ---------------------
    CLAIM_STALE = 6 * 3600  # a claim this old belongs to a keepgram that died

    def claim(self, chat_id: int, msg_ids: list[int]) -> bool:
        """True if these messages are now ours to copy; False if another keepgram
        is copying one of them right now."""
        now = time.time()
        with self.db:
            self.db.execute("DELETE FROM claims WHERE at < ?", (now - self.CLAIM_STALE,))
            # A keepgram whose window was closed mid-copy left its claim behind.
            for (pid,) in self.db.execute("SELECT DISTINCT pid FROM claims").fetchall():
                if pid != os.getpid() and not _alive(pid):
                    self.db.execute("DELETE FROM claims WHERE pid=?", (pid,))
            marks = ",".join("?" * len(msg_ids))
            busy = self.db.execute(f"SELECT 1 FROM claims WHERE chat_id=? AND msg_id IN ({marks}) AND pid != ?",
                                   (chat_id, *msg_ids, os.getpid())).fetchone()
            if busy:
                return False
            self.db.executemany("INSERT OR REPLACE INTO claims VALUES (?,?,?,?)",
                                [(chat_id, m, os.getpid(), now) for m in msg_ids])
        return True

    def release(self, chat_id: int, msg_ids: list[int]) -> None:
        with self.db:
            self.db.executemany("DELETE FROM claims WHERE chat_id=? AND msg_id=? AND pid=?",
                                [(chat_id, m, os.getpid()) for m in msg_ids])

    # -- posting journal (no duplicate copy after an interruption) -----------
    def begin_posting(self, chat_id: int, msg_ids: list[int]) -> None:
        now = time.time()
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO posting VALUES (?,?,?)",
                                [(chat_id, m, now) for m in msg_ids])

    def end_posting(self, chat_id: int, msg_ids: list[int]) -> None:
        with self.db:
            self.db.executemany("DELETE FROM posting WHERE chat_id=? AND msg_id=?", [(chat_id, m) for m in msg_ids])

    def posting_since(self, chat_id: int, msg_ids: list[int]) -> float | None:
        """When a copy of these began to be posted and was never recorded - None
        if that didn't happen."""
        marks = ",".join("?" * len(msg_ids))
        row = self.db.execute(f"SELECT MIN(started) FROM posting WHERE chat_id=? AND msg_id IN ({marks})",
                              (chat_id, *msg_ids)).fetchone()
        return row[0]

    # -- the watcher -------------------------------------------------------
    def mark(self, chat_id: int) -> int | None:
        row = self.db.execute("SELECT last_id FROM watch_marks WHERE chat_id=?", (chat_id,)).fetchone()
        return row[0] if row else None

    def set_mark(self, chat_id: int, last_id: int) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO watch_marks VALUES (?,?)", (chat_id, last_id))

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    def kept_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM kept").fetchone()[0]

    # -- upload ------------------------------------------------------------
    def target_for(self, root: str) -> int | None:
        row = self.db.execute("SELECT chat_id FROM upload_targets WHERE root=?", (root,)).fetchone()
        return row[0] if row else None

    def set_target(self, root: str, chat_id: int) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO upload_targets VALUES (?,?)", (root, chat_id))

    def uploaded_msg(self, chat_id: int, sha256: str, part: int, parts: int) -> int | None:
        row = self.db.execute(
            "SELECT msg_id FROM uploaded WHERE chat_id=? AND sha256=? AND part=? AND parts=?",
            (chat_id, sha256, part, parts),
        ).fetchone()
        return row[0] if row else None

    def mark_uploaded(self, chat_id: int, sha256: str, part: int, parts: int, rel: str, size: int, msg_id: int):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO uploaded VALUES (?,?,?,?,?,?,?,?)",
                (chat_id, sha256, part, parts, rel, size, msg_id, time.time()),
            )

    def uploaded_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM uploaded").fetchone()[0]

    def cached_hash(self, path: str, size: int, mtime_ns: int) -> str | None:
        row = self.db.execute(
            "SELECT sha256 FROM hashes WHERE path=? AND size=? AND mtime_ns=?", (path, size, mtime_ns)
        ).fetchone()
        return row[0] if row else None

    def store_hash(self, path: str, size: int, mtime_ns: int, sha256: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO hashes VALUES (?,?,?,?)", (path, size, mtime_ns, sha256))
