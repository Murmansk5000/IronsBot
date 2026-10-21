# SPDX-License-Identifier: MIT
"""Materialize original images, including GIFs, before durable unit registration."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, RemoteImagePart

if TYPE_CHECKING:
    from ironsbot.services.messaging.image_collage import ImageCollageService


async def materialize_media(
    message: OutboundMessage | None,
    collage: ImageCollageService,
) -> OutboundMessage | None:
    if message is None:
        return None
    semaphore = asyncio.Semaphore(collage.download_concurrency)

    async def freeze(part: BinaryImagePart | RemoteImagePart) -> BinaryImagePart:
        if isinstance(part, BinaryImagePart):
            return part
        async with semaphore:
            content = await collage.fetch_image(part.url, collage.max_source_bytes)
        if not content:
            msg = "Empty original media response"
            raise ValueError(msg)
        mime, extension = (
            ("image/gif", "gif")
            if content.startswith((b"GIF87a", b"GIF89a"))
            else ("image/webp", "webp")
            if content.startswith(b"RIFF")
            else ("image/jpeg", "jpg")
            if content.startswith(b"\xff\xd8")
            else ("image/png", "png")
        )
        return BinaryImagePart(content, mime, f"dynamic.{extension}")

    parts = await asyncio.gather(
        *(
            freeze(part)
            for part in message.parts
            if isinstance(part, (BinaryImagePart, RemoteImagePart))
        )
    )
    return OutboundMessage(tuple(parts))
