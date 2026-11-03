"""secure: every file in your chats that depends on someone else's post gets
posted again as your own upload.

    scan()  reads your chats oldest first and asks each finder plug-in about
            each message - nothing is changed; the jobs can be shown first
    run()   for each job: download, upload as your own (same kind of message,
            caption and formatting kept), check the copy, record it - and
            only then, if secure.replace is on, delete the forward
    tidy_plan() / tidy()
            later: delete the forwards that already have their own copy

What is done is read from the chats themselves, not only from data/state.db:
a copy already posted after its forward (by keepgram on another device, or
before the records were lost) is recorded, never copied again.

A job is never half done: if the upload or the check fails, nothing is
recorded or deleted and the next run tries again. Copies are sent silently
(no notification to members)."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field

from telethon.tl import types

from keepgram import config, media, paths, plugins, thumbs, transfer
from keepgram.chats import OwnedChat
from keepgram.media import (
    Progress,
    album_ok,
    caption_with_note,
    file_name,
    has_file,
    human,
    input_media_like,
    is_plain_file,
    size_of,
)
from keepgram.meter import Meter
from keepgram.state import State


@dataclass
class Job:
    chat: OwnedChat
    own: list  # the messages in your chat
    dep: plugins.Dependency


@dataclass
class ScanResult:
    jobs: list[Job] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    messages: int = 0


async def scan(client, chats: list[OwnedChat], owned_ids, cfg: dict, state: State, messages=None, progress=None,
               cancelled=None) -> ScanResult:
    """messages(chat) -> async iterator of the chat's messages, oldest first.
    The default reads the history (accounts only); the bot reads by message
    number instead. progress(result) is called every 100 messages; without it
    each chat's name is printed."""
    plugins.load()
    finders = [plugins.get("finder", name) for name in cfg["secure"]["finders"]]
    me = await client.get_me()
    ctx = plugins.Context(client, me.id, set(owned_ids), cfg)
    limit = config.file_limit(cfg)
    if messages is None:
        def messages(chat):
            return client.iter_messages(chat.entity, reverse=True)
    out = ScanResult()
    for chat in chats:
        if progress is None:
            print(f"  scanning {chat.title} ...", flush=True)
        await _collect(ctx, finders, chat, messages(chat), state, limit, out, progress, cancelled)
    return out


NOTE = "↪ kept from "


def is_keepgram_copy(msg) -> bool:
    """A copy keepgram posted (this one or another), told by its note even
    before - or without - a record of it: never a find, whatever links it holds."""
    text = msg.message or ""
    return msg.fwd_from is None and (text.startswith(NOTE) or f"\n{NOTE}" in text)


async def _collect(ctx, finders, chat, messages, state, limit, out: ScanResult, progress, cancelled) -> None:
    last: Job | None = None
    start = len(out.jobs)
    mine: dict = {}  # posts of yours with a file, by size: copies made before, maybe on another device
    async for msg in messages:
        if cancelled and cancelled():
            break
        out.messages += 1
        if progress and out.messages % 100 == 0:
            progress(out)
        # Not `msg.out`: in your own channel everything you posted is "out",
        # forwards included - those are exactly what this is for.
        if isinstance(msg, types.MessageService):
            continue
        if msg.out and msg.fwd_from is None and has_file(msg) and not state.is_copy(chat.id, msg.id):
            mine.setdefault(_size_key(msg), []).append(msg)
        if state.is_kept(chat.id, msg.id) or state.is_copy(chat.id, msg.id) or is_keepgram_copy(msg):
            continue
        dep = None
        for finder in finders:
            dep = await finder.find(ctx, msg)
            if dep:
                break
        if not dep:
            continue
        out.notes += [f"{chat.title} #{msg.id}: {n}" for n in dep.notes]
        for f in dep.files:
            if size_of(f) > limit:
                out.notes.append(
                    f"{chat.title} #{msg.id}: {human(size_of(f))} is over the {human(limit)} upload limit - not copied"
                )
        dep.files = [f for f in dep.files if size_of(f) <= limit]
        if not dep.files:
            continue
        # A forwarded album arrives as one message per item - keep it one album.
        if (
            last is not None
            and dep.finder == "forwarded"
            and last.dep.finder == "forwarded"
            and msg.grouped_id
            and last.own[-1].grouped_id == msg.grouped_id
            and len(last.dep.files) < 10
        ):
            last.own.append(msg)
            last.dep.files.extend(dep.files)
            continue
        last = Job(chat, [msg], dep)
        out.jobs.append(last)
    used: set[int] = set()
    out.jobs[start:] = [job for job in out.jobs[start:] if not _already_copied(job, mine, used, state)]


def _already_copied(job: Job, mine: dict, used: set[int], state: State) -> bool:
    """Look among your later posts in the chat for this job's copies, and record
    those found. True if every file of the job has its copy; otherwise the job
    is cut down to the files still missing. Each post stands for one file."""
    found: dict[int, object] = {}
    for i, f in enumerate(job.dep.files):
        for m in mine.get(_size_key(f), []):
            if m.id > job.own[0].id and m.id not in used and same_file(f, m):
                found[i] = m
                used.add(m.id)
                break
    return bool(found) and _record_found(job, found, state)


def _size_key(msg):
    return msg.media.document.size if isinstance(msg.media, types.MessageMediaDocument) else "photo"


def describe(result: ScanResult) -> str:
    lines = []
    per_chat: dict[str, list[Job]] = {}
    for job in result.jobs:
        per_chat.setdefault(job.chat.title, []).append(job)
    for title, jobs in per_chat.items():
        files = sum(len(j.dep.files) for j in jobs)
        size = sum(size_of(f) for j in jobs for f in j.dep.files)
        lines.append(f"  {title}: {files} file(s), {human(size)}")
    total = sum(len(j.dep.files) for j in result.jobs)
    size = sum(size_of(f) for j in result.jobs for f in j.dep.files)
    lines.append(f"  in all: {total} file(s), {human(size)} to download and upload again")
    return "\n".join(lines)


async def run(client, jobs: list[Job], cfg: dict, state: State, report=None, cancelled=None) -> tuple[int, list[str]]:
    """report(n, total, job) before each job; without it, progress is printed.
    media.METER follows the whole run: every file is downloaded and uploaded, so
    it counts twice its size."""
    def work(job) -> int:
        return 2 * sum(size_of(f) for f in job.dep.files)

    problems: list[str] = []
    clean_tmp()
    meter = Meter(sum(work(j) for j in jobs), len(jobs))
    outer, media.METER = media.METER, meter  # this run keeps its own hold on it (the bot runs several)
    try:
        return await _run(client, jobs, cfg, state, report, cancelled, work, problems, meter)
    finally:
        media.METER = outer
        await transfer.close(client)


async def _run(client, jobs, cfg, state, report, cancelled, work, problems, meter) -> tuple[int, list[str]]:
    done = 0
    for n, job in enumerate(jobs, 1):
        if cancelled and cancelled():
            break
        if report:
            report(n, len(jobs), job)
        else:
            print(f"[{n}/{len(jobs)}] {job.chat.title} #{job.own[0].id} - from {job.dep.source}")
        ids = [m.id for m in job.own]
        if all(state.is_kept(job.chat.id, i) for i in ids) or not state.claim(job.chat.id, ids):
            # another keepgram copied it after this one read the chat, or is copying it now
            meter.skip_unit(work(job))
            continue
        try:
            since = state.posting_since(job.chat.id, ids)
            if since is not None and await _recover(client, job, since, state):
                done += 1  # its copy was posted by an interrupted run - found and recorded, not posted again
                continue
            await _keep(client, job, cfg, state)
            done += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:  # one bad file never stops the rest
            problems.append(f"{job.chat.title} #{job.own[0].id}: {type(e).__name__}: {e}")
            if not report:
                print(f"  failed: {e}")
        finally:
            state.release(job.chat.id, ids)
            meter.finish_unit(work(job))
    return done, problems


async def _keep(client, job: Job, cfg: dict, state: State) -> None:
    sec = cfg["secure"]
    tmp = paths.TMP / uuid.uuid4().hex
    tmp.mkdir(parents=True)
    try:
        medias, captions, entities, downloaded = [], [], [], []
        for f in job.dep.files:
            thumb = await _thumb_for(client, f, tmp, thumbs.mode(cfg))
            if isinstance(f.media, types.MessageMediaDocument):
                # Streamed: each piece goes up as soon as it has come down, several
                # at a time, nothing on disk (unless a local copy is wanted).
                name = file_name(f) or f"file_{f.id}"
                disk = str(tmp / _safe(name)) if sec.get("local_copy_dir") else None
                prog = Progress(f"#{f.id} copying")
                handle = await transfer.copy_document(client, f, name, prog, disk)
                prog.end("copied")
                downloaded.append(disk)
                medias.append(await input_media_like(client, f, handle, thumb))
            else:  # a photo: small - download it, then upload it
                prog = Progress(f"#{f.id} download")
                path = await client.download_media(f, file=str(tmp), progress_callback=prog)
                prog.end("downloaded")
                if not path or not os.path.isfile(path):
                    raise RuntimeError(f"message {f.id}: nothing was downloaded")
                downloaded.append(path)
                prog = Progress(f"#{f.id} upload")
                medias.append(await input_media_like(client, f, path, thumb, prog))
                prog.end("uploaded")
            note = f"{NOTE}{job.dep.source} · {f.date:%Y-%m-%d}" if sec.get("source_note", True) else None
            text, ents = caption_with_note(f.message, f.entities, note)
            captions.append(text)
            entities.append(ents)

        # From here a copy may reach the chat; if this run dies before it is
        # recorded, the next run finds it (_recover) instead of posting another.
        state.begin_posting(job.chat.id, [m.id for m in job.own])
        together = album_ok(job.dep.files)
        batches = [list(range(len(medias)))] if together else [[i] for i in range(len(medias))]
        sent = []
        for batch in batches:
            if len(batch) == 1:
                i = batch[0]
                result = await client.send_file(
                    job.chat.entity, medias[i], caption=captions[i], formatting_entities=entities[i],
                    parse_mode=None, silent=True,
                )
                sent.append(result)
            else:
                result = await client.send_file(
                    job.chat.entity, [medias[i] for i in batch], caption=[captions[i] for i in batch],
                    formatting_entities=[entities[i] for i in batch], parse_mode=None, silent=True,
                )
                sent.extend(result)

        _check(job.dep.files, sent)

        for i, own in enumerate(job.own):
            new = sent[min(i, len(sent) - 1)]
            state.mark_kept(job.chat.id, own.id, new.id, job.dep.finder, job.dep.source)
        for extra in sent[len(job.own):]:
            # A link to an album: one message of yours, several copies - each is ours.
            state.mark_kept(job.chat.id, -extra.id, extra.id, job.dep.finder, job.dep.source)
        state.end_posting(job.chat.id, [m.id for m in job.own])

        if sec.get("local_copy_dir"):
            _local_copy(sec["local_copy_dir"], job, downloaded)

        if sec.get("replace") and job.dep.replaceable:
            await client.delete_messages(job.chat.entity, [m.id for m in job.own])
            for own in job.own:
                state.mark_removed(job.chat.id, own.id)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _thumb_for(client, f, tmp, mode: str) -> str | None:
    """A file sent as a file gets its kind's picture (unless the config says
    otherwise); a photo, video or song keeps its own, as Telegram shows it."""
    if not isinstance(f.media, types.MessageMediaDocument):
        return None  # a photo is its own picture
    plain = is_plain_file(f)
    if plain and mode == "logo":
        return thumbs.logo(file_name(f), f.media.document.mime_type)
    own = None
    if f.media.document.thumbs:
        try:
            own = await client.download_media(f, file=str(tmp / f"thumb_{f.id}.jpg"), thumb=-1)
        except Exception:
            own = None  # a copy without a thumbnail is still a copy
    if plain and own is None and mode == "own":
        return thumbs.logo(file_name(f), f.media.document.mime_type)
    return own


async def _recover(client, job: Job, since: float, state: State) -> bool:
    """A run was interrupted after it began posting this job's copy and before
    recording it. Look in the chat for what it posted - a keepgram copy (its
    note, not a forward, no record yet) of the same file (name and size, and
    the original caption), posted since then - and record those. True if every
    file of the job was found; otherwise the job is cut down to the files still
    missing, and they are copied as usual."""
    found: dict[int, object] = {}
    used: set[int] = set()
    async for m in client.iter_messages(job.chat.entity, limit=1000):
        if m.date is not None and m.date.timestamp() < since - 120:
            break
        if m.fwd_from or not has_file(m) or not is_keepgram_copy(m) or state.is_copy(job.chat.id, m.id):
            continue
        for i, f in enumerate(job.dep.files):
            if i not in found and m.id not in used and same_file(f, m):
                found[i] = m
                used.add(m.id)
                break
    if not found:
        return False
    return _record_found(job, found, state)


def _record_found(job: Job, found: dict, state: State) -> bool:
    """found: file index -> its copy in the chat. Record them; True if that's
    every file of the job, otherwise cut the job down to the missing ones."""
    aligned = len(job.own) == len(job.dep.files)  # a forwarded album: own[i] is files[i]
    for i, copy in found.items():
        own_id = job.own[i].id if aligned else -copy.id
        state.mark_kept(job.chat.id, own_id, copy.id, job.dep.finder, job.dep.source)
    if len(found) == len(job.dep.files):
        if not aligned:
            state.mark_kept(job.chat.id, job.own[0].id, found[0].id, job.dep.finder, job.dep.source)
        state.end_posting(job.chat.id, [m.id for m in job.own])
        return True
    keep = [i for i in range(len(job.dep.files)) if i not in found]
    job.dep.files = [job.dep.files[i] for i in keep]
    if aligned:
        state.end_posting(job.chat.id, [job.own[i].id for i in found])
        job.own = [job.own[i] for i in keep]
    return False


def same_file(original, copy, recorded: bool = False) -> bool:
    """Is `copy`, a post of yours, the same file as `original` with its caption?
    A file must have the same name, size and type: a copy is the very bytes.
    A photo is encoded again on upload, so it must have the same dimensions
    and, unless keepgram recorded it as the copy, carry keepgram's note with
    the original's date."""
    if copy.fwd_from is not None or not has_file(copy):
        return False
    if not (copy.message or "").startswith(original.message or ""):
        return False
    a, b = original.media, copy.media
    if isinstance(a, types.MessageMediaDocument) and isinstance(b, types.MessageMediaDocument):
        return (a.document.size == b.document.size and a.document.mime_type == b.document.mime_type
                and file_name(original) == file_name(copy))
    if isinstance(a, types.MessageMediaPhoto) and isinstance(b, types.MessageMediaPhoto):
        noted = is_keepgram_copy(copy) and f" · {original.date:%Y-%m-%d}" in copy.message
        return (recorded or noted) and _dims(a.photo) == _dims(b.photo)
    return False


def _dims(photo) -> tuple[int, int]:
    return max(((s.w, s.h) for s in photo.sizes if hasattr(s, "w")), key=lambda d: d[0] * d[1], default=(0, 0))


# -- tidy: delete forwards that have their own copy ---------------------------


@dataclass
class Tidy:
    chat: OwnedChat
    forwards: list[int]  # message ids, each with its copy checked just now


async def tidy_plan(client, chats: list[OwnedChat], state: State, progress=None) -> tuple[list[Tidy], list[str]]:
    """The forwards that are safe to delete: each one and its copy read again
    from the chat - the forward still there, the copy still there and the same
    file. A copy that's gone is forgotten, so the next copy run makes it again.
    Run scan() first: it records copies made elsewhere."""
    plan, notes = [], []
    for chat in chats:
        if progress:
            progress(chat)
        pairs = state.kept_forwards(chat.id)
        ok = []
        for at in range(0, len(pairs), 50):
            batch = pairs[at:at + 50]
            got = await client.get_messages(chat.entity, ids=[i for pair in batch for i in pair])
            got = {m.id: m for m in got if m is not None}
            for own_id, copy_id in batch:
                own, copy = got.get(own_id), got.get(copy_id)
                if own is None or own.fwd_from is None:
                    state.mark_removed(chat.id, own_id)  # already deleted
                elif copy is None or not same_file(own, copy, recorded=True):
                    state.forget(chat.id, own_id)
                    notes.append(f"{chat.title} #{own_id}: its copy is gone - kept, and copied again next time")
                else:
                    ok.append(own_id)
        if ok:
            plan.append(Tidy(chat, ok))
    return plan, notes


async def tidy(client, plan: list[Tidy], state: State, report=None, cancelled=None) -> int:
    """Delete the planned forwards, 100 at a time; report(done, total) after
    each batch. Returns how many were deleted."""
    total, done = sum(len(t.forwards) for t in plan), 0
    for t in plan:
        for at in range(0, len(t.forwards), 100):
            if cancelled and cancelled():
                return done
            batch = t.forwards[at:at + 100]
            await client.delete_messages(t.chat.entity, batch)
            for msg_id in batch:
                state.mark_removed(t.chat.id, msg_id)
            done += len(batch)
            if report:
                report(done, total)
    return done


def clean_tmp(older_than: float = 6 * 3600) -> None:
    """Temporary folders a run left behind when it was cut off (only a run
    keeping local copies, or copying photos, makes them)."""
    import time as _time

    if not paths.TMP.is_dir():
        return
    for entry in paths.TMP.iterdir():
        try:
            if entry.is_dir() and _time.time() - entry.stat().st_mtime > older_than:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def _check(originals, sent) -> None:
    """The copy is the same file: one message per file, same kind, same size."""
    if len(sent) != len(originals):
        raise RuntimeError(f"sent {len(sent)} message(s) for {len(originals)} file(s)")
    for old, new in zip(originals, sent, strict=True):
        if not has_file(new):
            raise RuntimeError(f"the copy of #{old.id} has no file")
        if isinstance(old.media, types.MessageMediaDocument):
            a, b = old.media.document.size, new.media.document.size
            if a != b:
                raise RuntimeError(f"the copy of #{old.id} is {b} bytes, the original {a}")


def _local_copy(root: str, job: Job, downloaded: list[str]) -> None:
    folder = os.path.join(os.path.expanduser(root), _safe(job.chat.title))
    os.makedirs(folder, exist_ok=True)
    for f, path in zip(job.dep.files, downloaded, strict=True):
        if not path:
            continue
        target = os.path.join(folder, f"{f.id}_{os.path.basename(path)}")
        if not os.path.exists(target):
            shutil.move(path, target)


def _safe(name: str) -> str:
    """A chat title as a folder name on any system (Windows is the strict one)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:100] or "chat"
