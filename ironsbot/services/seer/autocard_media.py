# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve versioned群星牌 artwork through the shared Seer image port."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
                    "autocard_role" if entry.kind == "role" else "autocard_card",
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
        return entry.to_outbound(image_contents=contents)
