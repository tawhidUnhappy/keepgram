"""register / get / items - one table per kind."""

from __future__ import annotations

from typing import Any

KINDS = ("finder", "sorter")

_table: dict[str, dict[str, Any]] = {kind: {} for kind in KINDS}
_origin: dict[tuple[str, str], str] = {}


def register(kind: str, obj: Any, origin: str | None = None) -> None:
    if kind not in _table:
        raise ValueError(f"unknown plug-in kind {kind!r} (known: {', '.join(KINDS)})")
    _table[kind][obj.name] = obj
    _origin[(kind, obj.name)] = origin or getattr(obj.find if kind == "finder" else obj.sort, "__module__", "?")


def get(kind: str, name: str) -> Any:
    try:
        return _table[kind][name]
    except KeyError:
        known = ", ".join(sorted(_table[kind])) or "none"
        raise SystemExit(f"no {kind} called {name!r} (known: {known})") from None


def items(kind: str) -> list[Any]:
    return sorted(_table[kind].values(), key=lambda o: (o.order, o.name))


def origin(kind: str, name: str) -> str:
    return _origin.get((kind, name), "?")
