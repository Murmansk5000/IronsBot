# SPDX-License-Identifier: MIT
"""Reusable asynchronous image collage orchestration."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

DEFAULT_MAX_IMAGES = 18
DEFAULT_MAX_SOURCE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_OUTPUT_SIDE = 12_000
DEFAULT_MAX_OUTPUT_PIXELS = 40_000_000
DEFAULT_DOWNLOAD_CONCURRENCY = 4
MIN_COLLAGE_IMAGES = 2
_DownloadedAsset = tuple[str, bytes | None, bool | None]
_PreparedGroup = tuple[tuple[tuple[str, bytes], ...], bool | None]


@dataclass(frozen=True, slots=True)
class PreparedImage:
    """One ordered image output, either composed bytes or an original URL."""

    url: str | None = None
    content: bytes | None = None
    content_type: str = "image/png"
    filename: str = "dynamic.png"

    def __post_init__(self) -> None:
        if (self.url is None) == (self.content is None):
            raise ValueError(  # noqa: TRY003
                "prepared images require exactly one source"
            )


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


class AnimatedCollageRenderer(Protocol):
    def __call__(self, image_bytes: Sequence[bytes]) -> bytes: ...


class ImageInspector(Protocol):
    def __call__(self, image_bytes: bytes) -> bool: ...


@dataclass(frozen=True, slots=True)
class ImageCollageService:
    """Download an ordered image set and compose it without blocking the loop."""

    fetch_image: Callable[[str, int], Awaitable[bytes]]
    render: ImageCollageRenderer
    render_animation: AnimatedCollageRenderer | None = None
    inspect_animation: ImageInspector | None = None
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

    async def prepare_urls(  # noqa: C901, PLR0915 - ordered mixed-media pipeline
        self, urls: Sequence[str]
    ) -> tuple[PreparedImage, ...]:
        """Compose consecutive media groups while preserving failed originals."""

        normalized = tuple(dict.fromkeys(url.strip() for url in urls if url.strip()))
        if not normalized:
            return ()
        semaphore = asyncio.Semaphore(self.download_concurrency)

        async def fetch(url: str) -> bytes | None:
            try:
                async with semaphore:
                    return await self.fetch_image(url, self.max_source_bytes)
            except ImageCollageError:
                return None

        downloaded = await asyncio.gather(*(fetch(url) for url in normalized))
        seen_content: set[str] = set()
        assets: list[tuple[str, bytes | None, bool | None]] = []
        for url, content in zip(normalized, downloaded, strict=True):
            if content is None:
                assets.append((url, None, None))
                continue
            digest = hashlib.sha256(content).hexdigest()
            if digest in seen_content:
                continue
            seen_content.add(digest)
            try:
                animated = await asyncio.to_thread(self._is_animated, content)
            except ImageCollageError:
                assets.append((url, None, None))
                continue
            assets.append((url, content, animated))

        outputs: list[PreparedImage] = []
        group: list[tuple[str, bytes]] = []
        group_animated: bool | None = None

        async def flush() -> None:
            nonlocal group, group_animated
            if not group:
                return
            if len(group) == 1:
                outputs.append(PreparedImage(url=group[0][0]))
            elif len(group) > self.max_images:
                outputs.extend(PreparedImage(url=item[0]) for item in group)
            else:
                try:
                    content = (
                        await self._compose_animation([item[1] for item in group])
                        if group_animated
                        else await self.compose_bytes([item[1] for item in group])
                    )
                except ImageCollageError:
                    outputs.extend(PreparedImage(url=item[0]) for item in group)
                else:
                    outputs.append(
                        PreparedImage(
                            content=content,
                            content_type="image/gif" if group_animated else "image/png",
                            filename="dynamic.gif" if group_animated else "dynamic.png",
                        )
                    )
            group = []
            group_animated = None

        for url, content, animated in assets:
            if content is None or animated is None:
                await flush()
                outputs.append(PreparedImage(url=url))
                continue
            if group_animated is not None and animated != group_animated:
                await flush()
            group_animated = animated
            group.append((url, content))
        await flush()
        return tuple(outputs)

    async def iter_prepared_urls(
        self, urls: Sequence[str]
    ) -> AsyncIterator[PreparedImage]:
        """Yield independently composed media groups as soon as each is ready."""

        normalized = tuple(dict.fromkeys(url.strip() for url in urls if url.strip()))
        if not normalized:
            return
        assets = await self._download_assets(normalized)
        tasks = [
            asyncio.ensure_future(self._prepare_group(items, animated=animated))
            for items, animated in _partition_groups(assets)
        ]
        try:
            for completed in asyncio.as_completed(tasks):
                for image in await completed:
                    yield image
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _download_assets(
        self,
        urls: Sequence[str],
    ) -> tuple[_DownloadedAsset, ...]:
        semaphore = asyncio.Semaphore(self.download_concurrency)

        async def fetch(url: str) -> bytes | None:
            try:
                async with semaphore:
                    return await self.fetch_image(url, self.max_source_bytes)
            except ImageCollageError:
                return None

        downloaded = await asyncio.gather(*(fetch(url) for url in urls))
        seen_content: set[str] = set()
        assets: list[_DownloadedAsset] = []
        for url, content in zip(urls, downloaded, strict=True):
            if content is None:
                assets.append((url, None, None))
                continue
            digest = hashlib.sha256(content).hexdigest()
            if digest in seen_content:
                continue
            seen_content.add(digest)
            try:
                animated = await asyncio.to_thread(self._is_animated, content)
            except ImageCollageError:
                assets.append((url, None, None))
                continue
            assets.append((url, content, animated))
        return tuple(assets)

    async def _prepare_group(
        self,
        group: Sequence[tuple[str, bytes]],
        *,
        animated: bool | None,
    ) -> tuple[PreparedImage, ...]:
        if animated is None or len(group) == 1:
            return (PreparedImage(url=group[0][0]),)
        if len(group) > self.max_images:
            return tuple(PreparedImage(url=url) for url, _content in group)
        try:
            content = (
                await self._compose_animation([item[1] for item in group])
                if animated
                else await self.compose_bytes([item[1] for item in group])
            )
        except ImageCollageError:
            return tuple(PreparedImage(url=url) for url, _content in group)
        return (
            PreparedImage(
                content=content,
                content_type="image/gif" if animated else "image/png",
                filename="dynamic.gif" if animated else "dynamic.png",
            ),
        )

    def _is_animated(self, content: bytes) -> bool:
        if self.inspect_animation is None:
            return False
        return self.inspect_animation(content)

    async def _compose_animation(self, images: Sequence[bytes]) -> bytes:
        if self.render_animation is None:
            raise ImageCollageError.animated()
        return await asyncio.to_thread(self.render_animation, tuple(images))

    def _validate_count(self, count: int) -> None:
        if not MIN_COLLAGE_IMAGES <= count <= self.max_images:
            raise ImageCollageError.invalid_count(count, self.max_images)


def _partition_groups(assets: Sequence[_DownloadedAsset]) -> tuple[_PreparedGroup, ...]:
    groups: list[_PreparedGroup] = []
    group: list[tuple[str, bytes]] = []
    group_animated: bool | None = None

    def flush() -> None:
        nonlocal group, group_animated
        if group:
            groups.append((tuple(group), group_animated))
        group = []
        group_animated = None

    for url, content, animated in assets:
        if content is None or animated is None:
            flush()
            groups.append((((url, b""),), None))
            continue
        if group_animated is not None and animated != group_animated:
            flush()
        group_animated = animated
        group.append((url, content))
    flush()
    return tuple(groups)
