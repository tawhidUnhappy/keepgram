#!/usr/bin/env bash
# keepgram's one entry point: builds .venv on first run (or when pyproject.toml
# changes), then runs the command. Everything stays inside this folder.
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
STAMP="$VENV/.keepgram-installed"

if [ ! -x "$PY" ] || [ "$ROOT/pyproject.toml" -nt "$STAMP" ]; then
    echo "[keepgram] setting up .venv ..."
    if command -v uv >/dev/null 2>&1; then
        export UV_CACHE_DIR="$ROOT/.cache/uv"
        [ -x "$PY" ] || uv venv -q --python 3.12 "$VENV"
        uv pip install -q --python "$PY" -e "$ROOT[fast]" 2>/dev/null \
            || uv pip install -q --python "$PY" -e "$ROOT"
    else
        [ -x "$PY" ] || python3 -m venv "$VENV"
        "$PY" -m pip install -q --upgrade pip
        "$PY" -m pip install -q -e "$ROOT[fast]" 2>/dev/null \
            || "$PY" -m pip install -q -e "$ROOT"
    fi
    touch "$STAMP"
fi

exec "$PY" -m keepgram.cli "$@"
