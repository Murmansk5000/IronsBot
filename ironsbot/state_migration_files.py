# SPDX-License-Identifier: MIT
"""Filesystem operations used by offline SQLite state migrations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def remove_sqlite_bundle(path: Path) -> None:
    """Remove a SQLite database and its optional WAL sidecars."""
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)


def remove_sqlite_bundles_under(root: Path, paths: Iterable[Path]) -> None:
    """Remove only legacy SQLite bundles contained in the configured data root."""
    for path in paths:
        if path.is_relative_to(root):
            remove_sqlite_bundle(path)
