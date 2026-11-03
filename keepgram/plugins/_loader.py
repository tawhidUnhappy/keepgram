"""Finding plug-ins: the built-ins, then the top-level plugins/ folder, then
installed packages (entry point group `keepgram.plugins`). A broken plug-in is
reported by `plugins` and skipped, never fatal."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import traceback
from importlib.metadata import entry_points

from keepgram import paths

BUILT_IN = ("forwarded", "post_link", "sorters")

_failures: list[tuple[str, str]] = []
_loaded = False


def load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for name in BUILT_IN:
        importlib.import_module(f"keepgram.plugins.{name}")
    folder = paths.PLUGINS
    if folder.is_dir():
        for entry in sorted(folder.iterdir()):
            if entry.name.startswith(("_", ".")):
                continue
            if entry.suffix == ".py":
                target = entry
            elif (entry / "__init__.py").is_file():
                target = entry / "__init__.py"
            else:
                continue
            mod_name = f"keepgram_user_plugin_{entry.stem}"
            try:
                spec = importlib.util.spec_from_file_location(
                    mod_name, target, submodule_search_locations=[str(entry)] if entry.is_dir() else None
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)
            except Exception:
                _failures.append((str(entry), traceback.format_exc(limit=3)))
    for ep in entry_points(group="keepgram.plugins"):
        try:
            ep.load()
        except Exception:
            _failures.append((f"entry point {ep.name}", traceback.format_exc(limit=3)))


def failures() -> list[tuple[str, str]]:
    return list(_failures)
