# SPDX-License-Identifier: MIT
"""HTTP and Pillow implementation for adaptive image collages."""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from httpx import HTTPStatusError, TransportError
from PIL import Image, ImageOps, UnidentifiedImageError

from ironsbot.services.messaging.image_collage import ImageCollageError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from httpx import AsyncClient

HTTP_SERVER_ERROR = 500
HTTP_RATE_LIMIT = 429


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
        failure = ImageCollageError.download_failed()
        failure.retryable = isinstance(
            error, (TransportError, TimeoutError, ConnectionError)
        ) or (
            isinstance(error, HTTPStatusError)
            and (
                error.response.status_code >= HTTP_SERVER_ERROR
                or error.response.status_code == HTTP_RATE_LIMIT
            )
        )
        raise failure from error
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
    horizontal: bool = False,
) -> bytes:
    decoded: list[_DecodedImage] = []
    try:
        remaining_pixels = max_pixels
        for data in image_bytes:
            image = _decode_image(data, remaining_pixels)
            decoded.append(image)
            remaining_pixels -= image.width * image.height
        rows = _choose_layout(
            decoded, max_side=max_side, max_pixels=max_pixels, horizontal=horizontal
        )
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


def _choose_layout(
    decoded: Sequence[_DecodedImage],
    *,
    max_side: int,
    max_pixels: int,
    horizontal: bool,
) -> tuple[tuple[tuple[int, int], ...], ...]:
    def candidate(columns: int):
        groups = tuple(
            decoded[index : index + columns]
            for index in range(0, len(decoded), columns)
        )
        ratios = [sum(image.width / image.height for image in row) for row in groups]
        relative_height = sum(1 / ratio for ratio in ratios)
        area = sum(image.width * image.height for image in decoded)
        width = math.sqrt(area / relative_height)
        height = width * relative_height
        scale = _output_scale(width, height, max_side=max_side, max_pixels=max_pixels)
        width *= scale
        height *= scale
        # Compare retained detail before rounded dimensions: rounding must not
        # make a needlessly narrow layout win a tie between equivalent grids.
        retention = min(
            (width / ratio / image.height) ** 2
            for row, ratio in zip(groups, ratios, strict=True)
            for image in row
        )
        smallest = min(
            (width / ratio) ** 2 * image.width / image.height
            for row, ratio in zip(groups, ratios, strict=True)
            for image in row
        )
        score = (
            round(retention, 9),
            round(smallest, 6),
            -abs(math.log(width / height)),
            -columns,
        )
        return score, _filled_rows(groups, ratios, max(columns, math.floor(width)))

    choices = (len(decoded),) if horizontal else range(1, len(decoded) + 1)
    return max((candidate(columns) for columns in choices), key=lambda item: item[0])[1]


def _filled_rows(
    groups: Sequence[Sequence[_DecodedImage]], ratios: Sequence[float], width: int
) -> tuple[tuple[tuple[int, int], ...], ...]:
    rows = []
    for group, ratio in zip(groups, ratios, strict=True):
        height = max(1, math.floor(width / ratio))
        # Reserve one pixel per image and distribute the rest proportionally.
        remaining = width - len(group)
        positions = [0]
        cumulative = 0.0
        for image in group:
            cumulative += image.width / image.height
            positions.append(round(remaining * cumulative / ratio))
        rows.append(
            tuple(
                (positions[index + 1] - positions[index] + 1, height)
                for index in range(len(group))
            )
        )
    return tuple(rows)


def _canvas_size(rows: Sequence[Sequence[tuple[int, int]]]) -> tuple[int, int]:
    return (
        max(sum(width for width, _height in row) for row in rows),
        sum(max(height for _width, height in row) for row in rows),
    )


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
    width: float,
    height: float,
    *,
    max_side: int,
    max_pixels: int,
) -> float:
    side_scale = min(max_side / width, max_side / height, 1.0)
    pixel_scale = min(math.sqrt(max_pixels / (width * height)), 1.0)
    return min(side_scale, pixel_scale)
