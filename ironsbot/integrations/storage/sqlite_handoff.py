# SPDX-License-Identifier: MIT
"""A stopped application's explicit SQLite snapshot for deployment rollback."""

from __future__ import annotations

import os
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from ironsbot.integrations.storage.sqlite import open_sqlite_connection


@dataclass(slots=True)
class SqliteHandoff:
    target: Path
    snapshot: Path
    saved: bool = False

    @classmethod
    def within(cls, root: Path, relative: str) -> SqliteHandoff:
        target = (root / relative).resolve()
        root = root.resolve()
        if (
            not target.is_relative_to(root)
            or target == root
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            message = "SQLite handoff must stay inside the data mount"
            raise ValueError(message)
        snapshot = root / "operations" / "migration-backup" / relative
        return cls(target, snapshot)

    def save(self) -> None:
        if not self.target.is_file():
            return
        self.snapshot.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.snapshot, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with (
            closing(open_sqlite_connection(self.target, read_only=True)) as source,
            closing(open_sqlite_connection(self.snapshot)) as backup,
        ):
            source.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                message = "SQLite deployment snapshot failed integrity check"
                raise ValueError(message)
        self.saved = True

    def restore(self) -> None:
        if not self.saved:
            return
        with (
            closing(open_sqlite_connection(self.snapshot, read_only=True)) as source,
            closing(open_sqlite_connection(self.target)) as target,
        ):
            source.backup(target)

    def finish(self) -> None:
        if self.saved:
            self.snapshot.unlink()
            self.saved = False
