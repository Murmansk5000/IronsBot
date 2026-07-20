# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Final

from anyio import Path as AsyncPath

if TYPE_CHECKING:
    from pathlib import Path

PET_CONFIG_IMAGE_SUFFIXES: Final = (".png", ".webp", ".jpg", ".jpeg")


class FilePetConfigImageStore:
    """Read locally maintained pet configuration images by pet ID."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    async def load(self, pet_id: int) -> bytes | None:
        if pet_id <= 0:
            return None

        for suffix in PET_CONFIG_IMAGE_SUFFIXES:
            path = AsyncPath(self._root / f"{pet_id}{suffix}")
            if await path.is_file():
                return await path.read_bytes()
        return None
