# SPDX-License-Identifier: MIT
"""Reusable asynchronous image collage orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

DEFAULT_MAX_IMAGES = 18
DEFAULT_MAX_SOURCE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_OUTPUT_SIDE = 12_000
DEFAULT_MAX_OUTPUT_PIXELS = 40_000_000
DEFAULT_DOWNLOAD_CONCURRENCY = 4
MIN_COLLAGE_IMAGES = 2


class ImageCollageError(RuntimeError):
    """Raised when a complete collage cannot be produced safely."""

    @classmethod
    def invalid_count(cls, count: int, maximum: int) -> ImageCollageError:
        return cls(f"image count {count} is outside 2..{maximum}")

    @classmethod
    def download_failed(cls) -> ImageCollageError:
        return cls("image download failed")

    @classmethod
    def invalid_content_type(cls) -> ImageCollageError:
        return cls("invalid image response content type")

    @classmethod
    def empty_response(cls) -> ImageCollageError:
        return cls("image response is empty")

    @classmethod
    def source_too_large(cls) -> ImageCollageError:
        return cls("image exceeds source byte limit")

    @classmethod
    def invalid_dimensions(cls) -> ImageCollageError:
        return cls("image dimensions are invalid")

    @classmethod
    def animated(cls) -> ImageCollageError:
        return cls("animated image cannot be collaged")

    @classmethod
    def decode_failed(cls) -> ImageCollageError:
        return cls("image decoding failed")

    @classmethod
    def render_failed(cls) -> ImageCollageError:
        return cls("image collage rendering failed")


class ImageCollageRenderer(Protocol):
    def __call__(
        self,
        image_bytes: Sequence[bytes],
        *,
        max_side: int,
        max_pixels: int,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ImageCollageService:
    """Download an ordered image set and compose it without blocking the loop."""

    fetch_image: Callable[[str, int], Awaitable[bytes]]
    render: ImageCollageRenderer
    max_images: int = DEFAULT_MAX_IMAGES
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    max_output_side: int = DEFAULT_MAX_OUTPUT_SIDE
    max_output_pixels: int = DEFAULT_MAX_OUTPUT_PIXELS
    download_concurrency: int = DEFAULT_DOWNLOAD_CONCURRENCY

    async def compose_urls(self, urls: Sequence[str]) -> bytes:
        normalized = tuple(url.strip() for url in urls if url.strip())
        self._validate_count(len(normalized))
        semaphore = asyncio.Semaphore(self.download_concurrency)

        async def fetch(url: str) -> bytes:
            async with semaphore:
                return await self.fetch_image(url, self.max_source_bytes)

        images = await asyncio.gather(*(fetch(url) for url in normalized))
        return await self.compose_bytes(images)

    async def compose_bytes(self, images: Sequence[bytes]) -> bytes:
        self._validate_count(len(images))
        return await asyncio.to_thread(
            self.render,
            tuple(images),
            max_side=self.max_output_side,
            max_pixels=self.max_output_pixels,
        )

    def _validate_count(self, count: int) -> None:
        if not MIN_COLLAGE_IMAGES <= count <= self.max_images:
            raise ImageCollageError.invalid_count(count, self.max_images)
