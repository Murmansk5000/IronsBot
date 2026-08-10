# SPDX-License-Identifier: MIT
"""Contracts for retrieving the current weekly preview image."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime


class WeeklyPreviewImageError(RuntimeError):
    @classmethod
    def from_detail(cls, detail: str) -> WeeklyPreviewImageError:
        return cls(detail)

    @classmethod
    def missing_cache_for_not_modified(
        cls,
        source_url: str,
    ) -> WeeklyPreviewImageError:
        return cls(f"304 Not Modified but local cache is unavailable ({source_url})")

    @classmethod
    def invalid_png(cls) -> WeeklyPreviewImageError:
        return cls("response is not a valid PNG image")

    @classmethod
    def image_too_large(cls, limit: int) -> WeeklyPreviewImageError:
        return cls(f"preview image exceeds {limit} bytes")


@dataclass(frozen=True, slots=True)
class WeeklyPreviewImage:
    data: bytes
    cached_at: datetime
    source_url: str
    stale: bool = False
    refresh_error: str = ""


class WeeklyPreviewImageSource(Protocol):
    async def fetch(self, primary_url: str) -> WeeklyPreviewImage: ...
