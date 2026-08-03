# SPDX-License-Identifier: MIT
"""Central paths for files that may be safely discarded between runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class CachePaths:
    """Expose named directories below one disposable cache root."""

    root: Path

    def render_dir(self) -> Path:
        return self._directory("render")

    def downloads_dir(self) -> Path:
        return self._directory("downloads")

    def http_dir(self) -> Path:
        return self._directory("http")

    def assets_dir(self) -> Path:
        return self._directory("assets")

    def runtime_dir(self) -> Path:
        return self._directory("runtime")

    def _directory(self, name: str) -> Path:
        return self.root / name
