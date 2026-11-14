# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-render asset quality and final-cache eligibility."""

from __future__ import annotations

import asyncio
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
from ironsbot.services.seer.render_pipeline import (
    current_render,
    mark_render_degraded,
    publish_render_cache,
)

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
    timeout_seconds: float = 45.0

    @property
    def complete(self) -> bool:
        return not self.failures

    async def fetch(self, kind: ImageKind, key: str, *, fallback: bool = True) -> bytes:
        del fallback
        try:
            async with asyncio.timeout(self.timeout_seconds):
                data = await self.source.fetch(kind, key, fallback=False)
            validate_image_data(data)
        except MissingImageRepositoryError:
            raise
        except (ImageSourceError, TimeoutError) as error:
            if not isinstance(error, ImageSourceError):
                error = ImageSourceError("图片素材准备超时")
            self.failures[kind, key] = error
            mark_render_degraded()
            return placeholder_image(kind)
        else:
            return data

    def entry(self, category: str, content_key: str) -> RenderCacheEntry:
        if (execution := current_render.get()) is not None:
            execution.cache_key = f"{category}:{content_key}"
        entry = self.cache.entry(category, content_key)

        def put(data: bytes) -> None:
            if self.complete:
                publish_render_cache(lambda: entry.put(data))

        return RenderCacheEntry(get=entry.get, put=put)
