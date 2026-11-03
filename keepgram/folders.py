"""Your channels and groups in Telegram chat folders: "Keepgram 1" until it is
full, then "Keepgram 2", and so on. Folders sync to every Telegram app.

Planning is plain data in, plain data out (plan()), so it can be tested and
shown before anything changes; apply() then sends only the folders that differ.
Run it again any time: a chat stays in the folder it is already in, new chats
fill the first folder with room, chats you no longer own leave, and a folder of
ours that ends up empty is removed. Folders not named "<name> <n>" are never
touched."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from telethon import errors, utils
from telethon.tl import functions, types

TITLE_LIMIT = 12  # Telegram's limit on a folder name
FIRST_ID, LAST_ID = 2, 255  # 0 is "All chats", 1 is the archive


@dataclass
class Existing:
    id: int
    title: str
    peer_ids: list[int]


@dataclass
class Planned:
    id: int
    title: str
    peer_ids: list[int]
    action: str  # "create" | "update" | "keep" | "delete"
    added: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)


def plan(groups: dict[str, list[int]], existing: list[Existing], size: int, taken: set[int] = frozenset()
         ) -> list[Planned]:
    """groups: series name -> chat ids, in the order new ones should be added.
    existing: the folders keepgram may manage. taken: the id of every folder on
    the account, of any type - a new folder must never reuse one."""
    taken_ids = {e.id for e in existing} | set(taken)
    out: list[Planned] = []
    for name, wanted_list in groups.items():
        pattern = re.compile(rf"^{re.escape(name)} (\d+)$")
        mine = sorted(
            ((int(m.group(1)), e) for e in existing if (m := pattern.match(e.title))),
            key=lambda pair: pair[0],
        )
        wanted = set(wanted_list)
        placed: set[int] = set()
        series: list[tuple[Existing, list[int]]] = []
        for _number, e in mine:
            # A chat stays where it is (and only once, if it got into two).
            keep = [p for p in e.peer_ids if p in wanted and p not in placed][:size]
            placed.update(keep)
            series.append((e, keep))
        waiting = [p for p in wanted_list if p not in placed]
        for _e, members in series:
            room = size - len(members)
            if room > 0 and waiting:
                members.extend(waiting[:room])
                waiting = waiting[room:]
        for e, members in series:
            added = [p for p in members if p not in e.peer_ids]
            removed = [p for p in e.peer_ids if p not in members]
            action = "delete" if not members else "update" if (added or removed) else "keep"
            out.append(Planned(e.id, e.title, members, action, added, removed))
        number = mine[-1][0] if mine else 0
        while waiting:
            number += 1
            free = [i for i in range(FIRST_ID, LAST_ID + 1) if i not in taken_ids]
            if not free:
                raise ValueError("no free folder ids left")
            taken_ids.add(free[0])
            members, waiting = waiting[:size], waiting[size:]
            out.append(Planned(free[0], f"{name} {number}", members, "create", added=list(members)))
    for p in out:
        if len(p.title) > TITLE_LIMIT:
            raise ValueError(f"folder name {p.title!r} is longer than Telegram's {TITLE_LIMIT} characters - "
                             "use a shorter folders.name")
    out.sort(key=lambda p: (_series_key(p.title), p.id))
    return out


def _series_key(title: str):
    head, _, num = title.rpartition(" ")
    return (head, int(num) if num.isdigit() else 0)


# -- Telegram -----------------------------------------------------------------


def _title(f) -> str:
    title = f.title
    return getattr(title, "text", title) or ""


async def _all_filters(client) -> dict[int, object]:
    result = await client(functions.messages.GetDialogFiltersRequest())
    return {f.id: f for f in getattr(result, "filters", result) if getattr(f, "id", None) is not None}


def _ours(f, title: str | None = None) -> bool:
    """A plain folder (not a shared one joined by link) - and, if given, with
    exactly this title."""
    return isinstance(f, types.DialogFilter) and (title is None or _title(f) == title)


async def read_existing(client) -> tuple[list[Existing], dict[int, object], set[int]]:
    """The plain folders (the only kind keepgram may manage), them raw, and
    the id of every folder of any kind."""
    filters = await _all_filters(client)
    existing, raw = [], {}
    for f in filters.values():
        if not _ours(f):
            continue  # shared folders (chatlists) are never ours, whatever their name
        ids = []
        for p in list(f.pinned_peers) + list(f.include_peers):
            pid = _peer_id(p)
            if pid is not None:
                ids.append(pid)
        existing.append(Existing(f.id, _title(f), ids))
        raw[f.id] = f
    return existing, raw, set(filters)


async def apply(client, plans: list[Planned], peers: dict[int, object], raw: dict[int, object],
                max_folders: int | None = None) -> list[str]:
    """Send the plan. peers: chat id -> InputPeer. Returns what went wrong, if
    anything (a full folder list, say), without stopping at the first.

    Telegram is read again first: a new folder goes only to an id that is still
    free, and a folder is changed or removed only if it is still a plain folder
    with the planned title - anything else is reported and left alone."""
    problems = []
    current = await _all_filters(client)
    room = None if max_folders is None else max_folders - sum(1 for f in current.values()
                                                              if not isinstance(f, types.DialogFilterDefault))
    for p in plans:
        if p.action == "keep":
            continue
        now = current.get(p.id)
        if p.action == "create" and now is not None:
            problems.append(f"{p.title}: folder id {p.id} is already used by \"{_title(now)}\" - left alone")
            continue
        if p.action == "create" and room is not None:
            if room <= 0:
                problems.append(f"{p.title}: your account may have {max_folders} folders and all are in use - "
                                "not made (Premium allows more; or remove a folder you don't need)")
                continue
            room -= 1
        if p.action in ("update", "delete") and not _ours(now, p.title):
            problems.append(f"{p.title}: that folder changed since it was read - left alone")
            continue
        try:
            if p.action == "delete":
                await client(functions.messages.UpdateDialogFilterRequest(id=p.id, filter=None))
                continue
            old = now if p.action == "update" else None
            pinned = []
            if old is not None:
                pinned = [x for x in old.pinned_peers if _peer_id(x) in p.peer_ids]
            pinned_ids = {_peer_id(x) for x in pinned}
            include = [peers[i] for i in p.peer_ids if i not in pinned_ids and i in peers]
            if old is not None:
                # Keep whatever else you set on it (an icon, a colour, ...).
                old.pinned_peers = pinned
                old.include_peers = include
                new = old
            else:
                new = types.DialogFilter(
                    id=p.id,
                    title=types.TextWithEntities(p.title, []),
                    pinned_peers=[],
                    include_peers=include,
                    exclude_peers=[],
                )
            await client(functions.messages.UpdateDialogFilterRequest(id=p.id, filter=new))
        except errors.RPCError as e:
            hint = ""
            if "FILTER" in str(e).upper() or "LIMIT" in str(e).upper():
                hint = " (Telegram allows 10 folders, 30 with Premium - and 100 chats per folder, 200 with Premium)"
            problems.append(f"{p.title}: {e}{hint}")
    return problems


def _peer_id(peer) -> int | None:
    try:
        return utils.get_peer_id(peer)
    except (TypeError, ValueError):
        return None
