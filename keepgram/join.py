"""join: name.ext.001, name.ext.002, ... back into name.ext.

Give it the .001 file, or a folder to join every set of parts in it. It never
overwrites a file that is already there, and prints the sha256 of what it made
- the same line is under every part on Telegram, so you can see it's whole."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from keepgram.media import Progress

_PART = re.compile(r"^(?P<base>.+)\.(?P<num>\d{3,})$")


def parts_of(first: Path) -> list[Path]:
    m = _PART.match(first.name)
    if not m or int(m.group("num")) != 1:
        raise SystemExit(f"{first} is not a first part (name.ext.001)")
    width = len(m.group("num"))
    out, k = [], 1
    while (p := first.with_name(f"{m.group('base')}.{k:0{width}d}")).is_file():
        out.append(p)
        k += 1
    return out


def join(first: Path) -> tuple[Path, str]:
    parts = parts_of(first)
    target = first.with_name(_PART.match(first.name).group("base"))
    if target.exists():
        raise SystemExit(f"{target} already exists - move it away first")
    total = sum(p.stat().st_size for p in parts)
    h = hashlib.sha256()
    prog = Progress(f"joining {len(parts)} parts into {target.name}")
    done = 0
    tmp = target.with_name(target.name + ".joining")
    with open(tmp, "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                while chunk := f.read(4 * 1024 * 1024):
                    out.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    prog(done, total)
    tmp.replace(target)
    prog.end("done")
    return target, h.hexdigest()


def firsts_in(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.rglob("*") if p.is_file() and (m := _PART.match(p.name)) and int(m.group("num")) == 1
    )
