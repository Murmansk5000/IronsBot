# SPDX-License-Identifier: MIT
"""HTTP and Pillow implementation for adaptive image collages."""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, UnidentifiedImageError

from ironsbot.services.messaging.image_collage import ImageCollageError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from httpx import AsyncClient

TARGET_ASPECT_RATIO = 4 / 3
ROW_FILL_PENALTY = 0.75


async def fetch_collage_image(
    client: AsyncClient,
    url: str,
    max_bytes: int,
) -> bytes:
    try:
        response = await client.get(url, timeout=15.0, follow_redirects=True)
        response.raise_for_status()
    except Exception as error:
        raise ImageCollageError.download_failed() from error

    content_type = response.headers.get("content-type", "").lower()
    if content_type and not content_type.startswith("image/"):
        raise ImageCollageError.invalid_content_type()
    data = response.content
    if not data:
        raise ImageCollageError.empty_response()
    if len(data) > max_bytes:
        raise ImageCollageError.source_too_large()
    return data


@dataclass(frozen=True, slots=True)
class _DecodedImage:
    image: Image.Image
    width: int
    height: int

    @property
    def aspect(self) -> float:
        return self.width / self.height


def render_adaptive_collage(
    image_bytes: Sequence[bytes],
    *,
    max_side: int,
    max_pixels: int,
) -> bytes:
    decoded = [_decode_image(data) for data in image_bytes]
    try:
        columns = _choose_columns([image.aspect for image in decoded])
        target_height = min(image.height for image in decoded)
        sizes = [
            (max(1, round(target_height * image.aspect)), target_height)
            for image in decoded
        ]
        rows = [
            sizes[index : index + columns]
            for index in range(0, len(sizes), columns)
        ]
        canvas_width = max(sum(width for width, _height in row) for row in rows)
        canvas_height = target_height * len(rows)
        scale = _output_scale(
            canvas_width,
            canvas_height,
            max_side=max_side,
            max_pixels=max_pixels,
        )
        if scale < 1:
            target_height = max(1, math.floor(target_height * scale))
            sizes = [
                (max(1, round(target_height * image.aspect)), target_height)
                for image in decoded
            ]
            rows = [
                sizes[index : index + columns]
                for index in range(0, len(sizes), columns)
            ]
            canvas_width = max(sum(width for width, _height in row) for row in rows)
            canvas_height = target_height * len(rows)

        canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
        image_index = 0
        for row_index, row in enumerate(rows):
            row_width = sum(width for width, _height in row)
            x = (canvas_width - row_width) // 2
            y = row_index * target_height
            for width, height in row:
                source = decoded[image_index].image
                resized = source.resize((width, height), Image.Resampling.LANCZOS)
                canvas.alpha_composite(resized, (x, y))
                x += width
                image_index += 1

        output = BytesIO()
        canvas.save(output, format="PNG", compress_level=6)
        return output.getvalue()
    except ImageCollageError:
        raise
    except Exception as error:
        raise ImageCollageError.render_failed() from error
    finally:
        for image in decoded:
            image.image.close()


def _decode_image(data: bytes) -> _DecodedImage:
    try:
        with Image.open(BytesIO(data)) as source:
            _ensure_static(source)
            source.load()
            normalized = ImageOps.exif_transpose(source).convert("RGBA")
    except ImageCollageError:
        raise
    except (OSError, UnidentifiedImageError) as error:
        raise ImageCollageError.decode_failed() from error
    if normalized.width <= 0 or normalized.height <= 0:
        normalized.close()
        raise ImageCollageError.invalid_dimensions()
    return _DecodedImage(normalized, normalized.width, normalized.height)


def _ensure_static(image: Image.Image) -> None:
    if bool(getattr(image, "is_animated", False)) and int(
        getattr(image, "n_frames", 1)
    ) > 1:
        raise ImageCollageError.animated()


def _choose_columns(aspects: Sequence[float]) -> int:
    best_columns = 1
    best_score = math.inf
    for columns in range(1, len(aspects) + 1):
        row_widths = [
            sum(aspects[index : index + columns])
            for index in range(0, len(aspects), columns)
        ]
        widest = max(row_widths)
        canvas_aspect = widest / len(row_widths)
        fill_penalty = sum((widest - width) / widest for width in row_widths)
        fill_penalty /= len(row_widths)
        score = abs(math.log(canvas_aspect / TARGET_ASPECT_RATIO))
        score += fill_penalty * ROW_FILL_PENALTY
        if score < best_score:
            best_score = score
            best_columns = columns
    return best_columns


def _output_scale(
    width: int,
    height: int,
    *,
    max_side: int,
    max_pixels: int,
) -> float:
    side_scale = min(max_side / width, max_side / height, 1.0)
    pixel_scale = min(math.sqrt(max_pixels / (width * height)), 1.0)
    return min(side_scale, pixel_scale)
