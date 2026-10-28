# SPDX-License-Identifier: MIT
"""Bilibili image formatting and closeable interactive media streams."""

from __future__ import annotations

import logging
from contextlib import aclosing
from typing import TYPE_CHECKING, Any

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, RemoteImagePart
from ironsbot.services.bilibili.parser import dynamic_image_urls

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ironsbot.services.messaging.image_collage import ImageCollageService

_LOGGER = logging.getLogger(__name__)


async def prepare_dynamic_image_message(
    item: dict[str, Any],
    collage: ImageCollageService | None,
    *,
    combine_images: bool = True,
) -> OutboundMessage | None:
    original = render_dynamic_image_message(item)
    if original is None or collage is None or not combine_images:
        return original
    urls = tuple(
        part.url for part in original.parts if isinstance(part, RemoteImagePart)
    )
    if len(urls) <= 1:
        return original
    prepared = await collage.prepare_urls(urls)
    parts = tuple(
        RemoteImagePart(image.url)
        if image.url is not None
        else BinaryImagePart(
            image.content or b"",
            image.content_type,
            image.filename,
        )
        for image in prepared
    )
    return OutboundMessage(parts) if parts else None


async def iter_dynamic_image_messages(
    item: dict[str, Any],
    collage: ImageCollageService | None,
    *,
    combine_images: bool = True,
) -> AsyncGenerator[OutboundMessage, None]:
    """Yield each prepared media group without waiting for slower groups."""

    original = render_dynamic_image_message(item)
    if original is None:
        return
    urls = tuple(
        part.url for part in original.parts if isinstance(part, RemoteImagePart)
    )
    if collage is None or not combine_images or len(urls) <= 1:
        for part in original.parts:
            yield OutboundMessage((part,))
        return
    async with aclosing(collage.iter_prepared_urls(urls)) as images:
        async for image in images:
            part = (
                RemoteImagePart(image.url)
                if image.url is not None
                else BinaryImagePart(
                    image.content or b"", image.content_type, image.filename
                )
            )
            yield OutboundMessage((part,))


def render_dynamic_image_message(item: dict[str, Any]) -> OutboundMessage | None:
    """Render dynamic source images independently from text delivery."""

    try:
        parts = tuple(
            RemoteImagePart(url)
            for raw_url in dynamic_image_urls(item)
            if (url := raw_url.strip().rstrip("]"))
        )
    except (TypeError, ValueError, KeyError):
        _LOGGER.exception("failed to render Bilibili dynamic images")
        return None
    return OutboundMessage(tuple(parts)) if parts else None
