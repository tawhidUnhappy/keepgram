"""Telegram's limits for this account, learned from Telegram - not typed into
settings. Whether you have Premium, how big a file can be, how many chats a
folder holds, how many folders you may have, how long a caption can be: all
read on connecting (help.getAppConfig + your account), cached in
data/limits.json for when there's no connection, and followed by everything
else. Get Premium, or let Telegram change a limit, and keepgram follows.

config "premium": "auto" (default) follows your account; true / false
overrides it."""

from __future__ import annotations

import json
import time

from telethon.tl import functions, types

from keepgram import paths

# Telegram's own values when nothing could be learned yet (as of 2026-11).
DEFAULTS = {
    "premium": False,
    "folders": 10, "folders_premium": 30,
    "chats_per_folder": 100, "chats_per_folder_premium": 200,
    "file_parts": 4000, "file_parts_premium": 8000,  # 512 KB parts
    "caption": 1024, "caption_premium": 4096,
}
_KEYS = {
    "folders": "dialog_filters_limit_default", "folders_premium": "dialog_filters_limit_premium",
    "chats_per_folder": "dialog_filters_chats_limit_default",
    "chats_per_folder_premium": "dialog_filters_chats_limit_premium",
    "file_parts": "upload_max_fileparts_default", "file_parts_premium": "upload_max_fileparts_premium",
    "caption": "caption_length_limit_default", "caption_premium": "caption_length_limit_premium",
}
PART = 512 * 1024
FILE = paths.DATA / "limits.json"


def _py(value):
    if isinstance(value, types.JsonObject):
        return {item.key: _py(item.value) for item in value.value}
    if isinstance(value, types.JsonArray):
        return [_py(v) for v in value.value]
    if isinstance(value, types.JsonNull):
        return None
    return getattr(value, "value", value)


def cached() -> dict:
    try:
        return {**DEFAULTS, **json.loads(FILE.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULTS)


async def learn(client, cfg: dict) -> dict:
    """Ask Telegram, remember the answer, and put it in cfg["_limits"].
    Never fails: without an answer, the last one (or Telegram's defaults) stays."""
    found = cached()
    try:
        result = await client(functions.help.GetAppConfigRequest(hash=0))
        app = _py(result.config) if isinstance(result, types.help.AppConfig) else {}
        for ours, theirs in _KEYS.items():
            if isinstance(app.get(theirs), (int, float)) and app[theirs] > 0:
                found[ours] = int(app[theirs])
        me = await client.get_me()
        found["premium"] = bool(getattr(me, "premium", False)) and not getattr(me, "bot", False)
        found["learned_at"] = time.time()
        paths.DATA.mkdir(parents=True, exist_ok=True)
        FILE.write_text(json.dumps(found, indent=2), encoding="utf-8")
    except Exception:  # offline, or a bot that may not ask - the cached answer is fine
        pass
    cfg["_limits"] = found
    from keepgram import media

    media.CAPTION_LIMIT = caption(cfg)
    return found


def premium(cfg: dict) -> bool:
    setting = cfg.get("premium", "auto")
    if isinstance(setting, bool):
        return setting
    return bool(cfg.get("_limits", cached()).get("premium"))


def _get(cfg: dict, name: str) -> int:
    lim = cfg.get("_limits") or cached()
    return int(lim[f"{name}_premium" if premium(cfg) else name])


def file_bytes(cfg: dict) -> int:
    return _get(cfg, "file_parts") * PART


def chats_per_folder(cfg: dict) -> int:
    return _get(cfg, "chats_per_folder")


def folders(cfg: dict) -> int:
    return _get(cfg, "folders")


def caption(cfg: dict) -> int:
    return _get(cfg, "caption")
