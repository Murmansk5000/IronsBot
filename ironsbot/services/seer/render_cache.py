# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RenderCacheEntry:
    """A single render's version-bound cache operations."""

    get: Callable[[], bytes | None]
    put: Callable[[bytes], None]


class RenderCache(Protocol):
    def entry(self, category: str, content_key: str) -> RenderCacheEntry: ...
