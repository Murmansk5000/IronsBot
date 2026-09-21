# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-render asset quality and final-cache eligibility."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.services.seer.images import (
    ImageKind,
    ImageSourceError,
    MissingImageRepositoryError,
    placeholder_image,
    validate_image_data,
)
from ironsbot.services.seer.render_cache import RenderCacheEntry

if TYPE_CHECKING:
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache


@dataclass
class RenderAssetSession:
    """Only presentation callers may substitute unavailable source images."""

    source: SeerImageSource
    cache: RenderCache
    failures: dict[tuple[ImageKind, str], ImageSourceError] = field(
        default_factory=dict
    )

    @property
    def complete(self) -> bool:
        return not self.failures

    async def fetch(self, kind: ImageKind, key: str, *, fallback: bool = True) -> bytes:
        del fallback
        try:
            data = await self.source.fetch(kind, key, fallback=False)
            validate_image_data(data)
        except MissingImageRepositoryError:
            raise
        except ImageSourceError as error:
            self.failures[kind, key] = error
            return placeholder_image(kind)
        else:
            return data

    def entry(self, category: str, content_key: str) -> RenderCacheEntry:
        entry = self.cache.entry(category, content_key)

        def put(data: bytes) -> None:
            if self.complete:
                entry.put(data)

        return RenderCacheEntry(get=entry.get, put=put)
