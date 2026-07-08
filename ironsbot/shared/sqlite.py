# SPDX-License-Identifier: MIT
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

RowFactory = Callable[[sqlite3.Cursor, Sequence[Any]], object]


def resolve_sqlite_path(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved


def connect_sqlite(
    path: str | Path,
    *,
    row_factory: RowFactory | None = None,
    pragmas: bool = True,
) -> sqlite3.Connection:
    resolved = resolve_sqlite_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved)
    if pragmas:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    if row_factory is not None:
        conn.row_factory = row_factory
    return conn


__all__ = ["connect_sqlite", "resolve_sqlite_path"]
