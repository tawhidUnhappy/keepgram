"""config.json: one flat-ish file, every key optional - anything missing comes
from DEFAULTS. config.example.json lists the same keys."""

from __future__ import annotations

import copy
import json
import os
from typing import Any

from keepgram import paths

DEFAULTS: dict[str, Any] = {
    # From https://my.telegram.org -> API development tools. Your own app, so
    # your own limits; never share the hash.
    "api_id": 0,
    "api_hash": "",
    # "auto": follow the account (keepgram asks Telegram - limits.py); true /
    # false to override. Premium doubles the file size, chats per folder, and more.
    "premium": "auto",
    # The picture beside a file keepgram sends as a file: logo (a picture of its
    # kind), own (keep a thumbnail the file already has), none. Photos and videos
    # sent as media always show as Telegram shows them.
    "thumbnails": "logo",
    # Only chats you created, unless this is on: then chats you are an admin of too.
    "include_admin_chats": False,
    "folders": {
        # Folders are "<name> 1", "<name> 2", ... - Telegram allows 12 characters
        # for a folder name, so keep this short.
        "name": "Keepgram",
        # How chats are split into series: one_series, by_type (plug-ins add more).
        "sorter": "one_series",
        # Chats per folder; 0 = Telegram's limit (100, or 200 with Premium).
        "size": 0,
    },
    "secure": {
        # What makes a message depend on someone else (plug-ins add more).
        "finders": ["forwarded", "post_link"],
        # A forward from one of your own chats isn't someone else's - skip it.
        "skip_own_sources": True,
        # Delete the forward / bare link once your own copy is posted and checked.
        "replace": False,
        # Add "kept from <where> · <date>" under the caption of the copy.
        "source_note": True,
        # Also keep every file on this disk folder ("" = don't).
        "local_copy_dir": "",
    },
    "watch": {
        # Keep the folders up to date as you make or leave chats.
        "folders": True,
        # Copy new forwards in your chats as they are posted.
        "keep_new": True,
        # Look through every chat again this often, for anything Telegram didn't announce.
        "every_minutes": 10,
    },
    "bot": {
        # From @BotFather. Run `bot` and it asks for it.
        "token": "",
        # Telegram user ids allowed to use the bot; empty = anyone.
        "allowed_users": [],
        # "Keep all old files" jobs running at once - each one downloads and
        # uploads through the machine the bot runs on.
        "max_jobs": 2,
    },
    "menus": {
        # keepgram-dark or keepgram-light - the Android look, in keepgram's colours.
        "look": "keepgram-dark",
    },
    "upload": {
        # Send every file as a file, byte for byte (photos and videos are not
        # recompressed). Off: photos/videos go up as media, the way apps send them.
        "as_files": True,
        # Skip files and folders whose name starts with "."
        "skip_hidden": True,
        # Size of each part for files over the limit; 0 = the limit itself.
        "part_mb": 0,
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load() -> dict[str, Any]:
    if not paths.CONFIG.is_file():
        return copy.deepcopy(DEFAULTS)
    with open(paths.CONFIG, encoding="utf-8") as f:
        return _merge(DEFAULTS, json.load(f))


def save(cfg: dict[str, Any]) -> None:
    paths.CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = paths.CONFIG.with_suffix(".json.tmp")
    # Keys starting with "_" are learned at run time (cfg["_limits"]), never saved.
    plain = {k: v for k, v in cfg.items() if not k.startswith("_")}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(plain, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, paths.CONFIG)
    # It holds the api hash. A no-op on Windows, which is fine.
    os.chmod(paths.CONFIG, 0o600)


MB = 1024 * 1024


def file_limit(cfg: dict[str, Any]) -> int:
    """Telegram's biggest single file for this account, in bytes - as Telegram
    says (limits.py): 2000 MB, or 4000 MB with Premium, today."""
    from keepgram import limits

    return limits.file_bytes(cfg)


def folder_size(cfg: dict[str, Any]) -> int:
    from keepgram import limits

    size = int(cfg["folders"].get("size") or 0)
    most = limits.chats_per_folder(cfg)
    return min(size, most) if size else most
