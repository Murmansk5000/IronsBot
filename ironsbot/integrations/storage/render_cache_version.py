# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a stable version key for disposable rendered-image caches."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from .render_cache import UNKNOWN_RENDER_CACHE_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path


class RenderCacheVersion:
    """Combine the published Seer version with rendering inputs at startup."""

    def __init__(
        self,
        data_version_getter: Callable[[], str],
        rendering_inputs: Iterable[Path],
    ) -> None:
        self._data_version_getter = data_version_getter
        self._rendering_fingerprint = _fingerprint_paths(rendering_inputs)

    def __call__(self) -> str:
        return self.for_version(self._data_version_getter())

    def for_version(self, data_version: str) -> str:
        """Apply the same renderer fingerprint to a captured release version."""
        if data_version == UNKNOWN_RENDER_CACHE_VERSION:
            return UNKNOWN_RENDER_CACHE_VERSION
        return f"{data_version}:{self._rendering_fingerprint}"


def _fingerprint_paths(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for index, root in enumerate(paths):
        for path in _iter_files(root):
            digest.update(f"{index}:{path.relative_to(root)}\0".encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _iter_files(root: Path) -> tuple[Path, ...]:
    if root.is_file():
        return (root,)
    return tuple(
        sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    )
