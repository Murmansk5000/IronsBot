# SPDX-License-Identifier: MIT
"""Atomic configuration handoff paired with supervised container rollback."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ConfigurationHandoff:
    target: Path
    candidate: Path
    backup: Path

    @classmethod
    def for_files(cls, target: Path, candidate: Path) -> "ConfigurationHandoff":
        return cls(
            target,
            candidate,
            target.with_name(f".{target.name}.{uuid4().hex}.rollback"),
        )

    def apply(self) -> None:
        if (
            self.target.parent.resolve() != self.candidate.parent.resolve()
            or self.target == self.candidate
            or self.target.is_symlink()
            or self.candidate.is_symlink()
            or not self.target.is_file()
            or not self.candidate.is_file()
        ):
            message = (
                "Configuration handoff requires distinct regular files in one directory"
            )
            raise ValueError(message)
        stat = self.target.stat()
        shutil.copy2(self.target, self.backup)
        if hasattr(os, "chown"):
            os.chown(self.backup, stat.st_uid, stat.st_gid)
            os.chown(self.candidate, stat.st_uid, stat.st_gid)
        self.candidate.chmod(stat.st_mode)
        self.candidate.replace(self.target)

    def restore(self) -> None:
        if self.backup.exists():
            self.backup.replace(self.target)

    def finish(self) -> None:
        self.backup.unlink(missing_ok=True)
