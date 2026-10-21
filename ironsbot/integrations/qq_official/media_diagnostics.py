# SPDX-License-Identifier: MIT
"""Read-only image and upload diagnostics; no URLs, tokens or image bytes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, UnidentifiedImageError

from ironsbot.core.delivery_attempt import delivery_unit

if TYPE_CHECKING:
    from qqbot_agent_sdk.dto import UploadPrepareResponse

logger = logging.getLogger(__name__)


def log_media_metadata(file_path: str) -> None:
    path = Path(file_path)
    size = path.stat().st_size
    try:
        with Image.open(path) as image:
            logger.info(
                "QQ upload media: unit=%s bytes=%d format=%s "
                "width=%d height=%d frames=%d",
                delivery_unit.get(),
                size,
                image.format,
                image.width,
                image.height,
                getattr(image, "n_frames", 1),
            )
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as error:
        logger.warning(
            "QQ upload media metadata unavailable: unit=%s bytes=%d exception=%s",
            delivery_unit.get(),
            size,
            type(error).__name__,
        )


def log_upload_parts(file_size: int, prepared: UploadPrepareResponse) -> None:
    sizes = tuple(
        min(
            part.block_size or prepared.block_size,
            max(0, file_size - (part.index - 1) * prepared.block_size),
        )
        for part in prepared.parts
    )
    logger.info(
        "QQ upload prepared: unit=%s bytes=%d parts=%d block_size=%d part_sizes=%s",
        delivery_unit.get(),
        file_size,
        len(prepared.parts),
        prepared.block_size,
        sizes,
    )
