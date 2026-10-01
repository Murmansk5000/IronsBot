# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve versioned群星牌 artwork through the shared Seer image port."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, UnidentifiedImageError

if TYPE_CHECKING:
    from ironsbot.core.outbound import OutboundMessage

    from .autocard import AutocardEntry
    from .images import SeerImageSource


@dataclass(frozen=True, slots=True)
class AutocardMediaService:
    images: SeerImageSource

    async def outbound(
        self,
        entry: AutocardEntry,
        *,
        include_additional_images: bool = True,
    ) -> OutboundMessage:
        keys = (
            entry.image_keys
            if include_additional_images
            else ((entry.image_key,) if entry.image_key else ())
        )
        results = await asyncio.gather(
            *(
                self.images.fetch(
                    "autocard_chip"
                    if entry.kind == "chip"
                    else "autocard_role"
                    if entry.kind == "role"
                    else "autocard_card",
                    key,
                    fallback=False,
                )
                for key in keys
            ),
            return_exceptions=True,
        )
        contents = tuple(
            result for result in results if isinstance(result, bytes) and result
        )
        if entry.kind == "chip":
            contents = tuple(
                image for content in contents if (image := _chip_preview(content))
            )
        return entry.to_outbound(image_contents=contents)


def _chip_preview(content: bytes) -> bytes | None:
    # Official chip glyphs are white and need a dark background in chat clients.
    try:
        with Image.open(BytesIO(content)) as source:
            icon = ImageOps.contain(source.convert("RGBA"), (224, 224))
            canvas = Image.new("RGB", (256, 256), (32, 36, 44))
            canvas.paste(
                icon, ((256 - icon.width) // 2, (256 - icon.height) // 2), icon
            )
            output = BytesIO()
            canvas.save(output, format="PNG")
            return output.getvalue()
    except (OSError, ValueError, UnidentifiedImageError):
        return None
