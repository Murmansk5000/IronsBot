# SPDX-License-Identifier: MIT
"""HTTP and Pillow implementation for adaptive image collages."""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from statistics import median
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, UnidentifiedImageError

from ironsbot.services.messaging.image_collage import ImageCollageError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from httpx import AsyncClient

MAX_IMAGE_UPSCALE = 2


async def fetch_collage_image(
    client: AsyncClient,
    url: str,
    max_bytes: int,
) -> bytes:
    try:
        async with client.stream(
            "GET", url, timeout=15.0, follow_redirects=True
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not content_type.startswith("image/"):
                raise ImageCollageError.invalid_content_type()  # noqa: TRY301 - retain typed download errors
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ImageCollageError.source_too_large()  # noqa: TRY301 - stop streaming at the limit
    except ImageCollageError:
        raise
    except Exception as error:
        raise ImageCollageError.download_failed() from error
    if not data:
        raise ImageCollageError.empty_response()
    return bytes(data)


@dataclass(frozen=True, slots=True)
class _DecodedImage:
    image: Image.Image
    width: int
    height: int


def render_adaptive_collage(
    image_bytes: Sequence[bytes],
    *,
    max_side: int,
    max_pixels: int,
) -> bytes:
    decoded: list[_DecodedImage] = []
    try:
        remaining_pixels = max_pixels
        for data in image_bytes:
            image = _decode_image(data, remaining_pixels)
            decoded.append(image)
            remaining_pixels -= image.width * image.height
        target_height = math.floor(median(image.height for image in decoded))
        sizes = []
        for image in decoded:
            image_scale = min(target_height / image.height, MAX_IMAGE_UPSCALE)
            sizes.append(
                (
                    max(1, round(image.width * image_scale)),
                    max(1, round(image.height * image_scale)),
                )
            )
        columns = _choose_columns(sizes)
        rows = _make_rows(sizes, columns)
        canvas_width, canvas_height = _canvas_size(rows)
        scale = _output_scale(
            canvas_width,
            canvas_height,
            max_side=max_side,
            max_pixels=max_pixels,
        )
        if scale < 1:
            sizes = [
                (max(1, math.floor(width * scale)), max(1, math.floor(height * scale)))
                for width, height in sizes
            ]
            rows = _make_rows(sizes, columns)
            canvas_width, canvas_height = _canvas_size(rows)
        if (
            max(canvas_width, canvas_height) > max_side
            or canvas_width * canvas_height > max_pixels
        ):
            raise ImageCollageError.source_too_large()  # noqa: TRY301 - validate rounded output dimensions
        return _render_rows(decoded, rows, (canvas_width, canvas_height))
    except ImageCollageError:
        raise
    except Exception as error:
        raise ImageCollageError.render_failed() from error
    finally:
        for image in decoded:
            image.image.close()


def _decode_image(data: bytes, max_pixels: int) -> _DecodedImage:
    try:
        with Image.open(BytesIO(data)) as source:
            _ensure_static(source)
            if source.width * source.height > max_pixels:
                raise ImageCollageError.source_too_large()
            source.load()
            normalized = ImageOps.exif_transpose(source).convert("RGBA")
    except ImageCollageError:
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ImageCollageError.decode_failed() from error
    if normalized.width <= 0 or normalized.height <= 0:
        normalized.close()
        raise ImageCollageError.invalid_dimensions()
    return _DecodedImage(normalized, normalized.width, normalized.height)


def _ensure_static(image: Image.Image) -> None:
    if (
        bool(getattr(image, "is_animated", False))
        and int(getattr(image, "n_frames", 1)) > 1
    ):
        raise ImageCollageError.animated()


def _make_rows(
    sizes: Sequence[tuple[int, int]], columns: int
) -> tuple[tuple[tuple[int, int], ...], ...]:
    return tuple(
        tuple(sizes[index : index + columns]) for index in range(0, len(sizes), columns)
    )


def _canvas_size(rows: Sequence[Sequence[tuple[int, int]]]) -> tuple[int, int]:
    return (
        max(sum(width for width, _height in row) for row in rows),
        sum(max(height for _width, height in row) for row in rows),
    )


def _choose_columns(sizes: Sequence[tuple[int, int]]) -> int:
    def score(columns: int) -> tuple[int, int, int, int]:
        width, height = _canvas_size(_make_rows(sizes, columns))
        return width + height, width * height, max(width, height), columns

    return min(range(1, len(sizes) + 1), key=score)


def _render_rows(
    decoded: Sequence[_DecodedImage],
    rows: Sequence[Sequence[tuple[int, int]]],
    canvas_size: tuple[int, int],
) -> bytes:
    with Image.new("RGBA", canvas_size, (0, 0, 0, 0)) as canvas:
        image_index = 0
        y = 0
        for row in rows:
            row_height = max(height for _width, height in row)
            x = (canvas.width - sum(width for width, _height in row)) // 2
            for width, height in row:
                source = decoded[image_index].image
                with source.resize(
                    (width, height), Image.Resampling.LANCZOS
                ) as resized:
                    canvas.alpha_composite(resized, (x, y + (row_height - height) // 2))
                x += width
                image_index += 1
            y += row_height
        output = BytesIO()
        canvas.save(output, format="PNG", compress_level=6)
        return output.getvalue()


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
