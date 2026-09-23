# SPDX-License-Identifier: MIT
"""Pillow implementation for vertically stacked animated media."""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, UnidentifiedImageError

from ironsbot.services.messaging.image_collage import ImageCollageError

if TYPE_CHECKING:
    from collections.abc import Sequence

MAX_DURATION_MS = 10_000
MAX_OUTPUT_BYTES = 20 * 1024 * 1024
MIN_ANIMATION_IMAGES = 2
ALPHA_THRESHOLD = 128
_QUALITY_STEPS = (
    (1280, 4096, 4_000_000, 100, 256),
    (1024, 3200, 3_000_000, 80, 192),
    (768, 2400, 2_000_000, 60, 96),
    (480, 1600, 1_000_000, 40, 32),
)


@dataclass(slots=True)
class _Animation:
    frames: list[Image.Image]
    starts: list[int]
    duration: int
    width: int
    height: int

    def frame_at(self, timestamp: int) -> Image.Image:
        position = timestamp % self.duration
        return self.frames[max(0, bisect_right(self.starts, position) - 1)]

    def close(self) -> None:
        for frame in self.frames:
            frame.close()


def inspect_animation(image_bytes: bytes) -> bool:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            return bool(getattr(image, "is_animated", False)) and int(
                getattr(image, "n_frames", 1)
            ) > 1
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ImageCollageError.decode_failed() from error


def render_vertical_animation(image_bytes: Sequence[bytes]) -> bytes:
    animations: list[_Animation] = []
    try:
        animations = [_decode_animation(data) for data in image_bytes]
        if len(animations) < MIN_ANIMATION_IMAGES:
            raise ImageCollageError.invalid_count(  # noqa: TRY301
                len(animations), 18
            )
        for max_width, max_height, max_pixels, max_frames, colors in _QUALITY_STEPS:
            rendered = _render_quality(
                animations,
                max_width=max_width,
                max_height=max_height,
                max_pixels=max_pixels,
                max_frames=max_frames,
                colors=colors,
            )
            if len(rendered) <= MAX_OUTPUT_BYTES:
                return rendered
        raise ImageCollageError.render_failed()  # noqa: TRY301
    except ImageCollageError:
        raise
    except Exception as error:
        raise ImageCollageError.render_failed() from error
    finally:
        for animation in animations:
            animation.close()


def _decode_animation(data: bytes) -> _Animation:
    frames: list[Image.Image] = []
    starts: list[int] = []
    elapsed = 0
    try:
        with Image.open(BytesIO(data)) as source:
            if not inspect_animation(data):
                raise ImageCollageError.animated()
            width, height = source.size
            for index in range(int(getattr(source, "n_frames", 1))):
                source.seek(index)
                starts.append(elapsed)
                duration = max(20, int(source.info.get("duration", 100) or 100))
                elapsed += duration
                frames.append(ImageOps.exif_transpose(source).convert("RGBA"))
    except ImageCollageError:
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ImageCollageError.decode_failed() from error
    if width <= 0 or height <= 0 or elapsed <= 0 or not frames:
        for frame in frames:
            frame.close()
        raise ImageCollageError.invalid_dimensions()
    return _Animation(frames, starts, elapsed, width, height)


def _render_quality(  # noqa: PLR0913 - explicit output quality limits
    animations: Sequence[_Animation],
    *,
    max_width: int,
    max_height: int,
    max_pixels: int,
    max_frames: int,
    colors: int,
) -> bytes:
    source_width = max(animation.width for animation in animations)
    source_height = sum(animation.height for animation in animations)
    scale = min(
        1.0,
        max_width / source_width,
        max_height / source_height,
        math.sqrt(max_pixels / (source_width * source_height)),
    )
    width = max(1, math.floor(source_width * scale))
    row_sizes = [
        (
            max(1, math.floor(animation.width * scale)),
            max(1, math.floor(animation.height * scale)),
        )
        for animation in animations
    ]
    height = sum(row_height for _row_width, row_height in row_sizes)
    duration = min(MAX_DURATION_MS, max(animation.duration for animation in animations))
    timestamps = _timeline(animations, duration, max_frames)
    frames: list[Image.Image] = []
    try:
        for timestamp in timestamps:
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            y = 0
            for animation, (row_width, row_height) in zip(
                animations, row_sizes, strict=True
            ):
                frame = animation.frame_at(timestamp).resize(
                    (row_width, row_height), Image.Resampling.LANCZOS
                )
                canvas.alpha_composite(frame, ((width - row_width) // 2, y))
                frame.close()
                y += row_height
            indexed = canvas.convert("RGB").quantize(
                colors=min(colors, 255),
                method=Image.Quantize.MEDIANCUT,
                dither=Image.Dither.FLOYDSTEINBERG,
            )
            alpha = canvas.getchannel("A")
            transparent = alpha.point(
                [255 if value < ALPHA_THRESHOLD else 0 for value in range(256)]
            )
            indexed.paste(255, mask=transparent)
            frames.append(indexed)
            canvas.close()
        durations = [
            timestamps[index + 1] - timestamp
            if index + 1 < len(timestamps)
            else duration - timestamp
            for index, timestamp in enumerate(timestamps)
        ]
        output = BytesIO()
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            disposal=2,
            transparency=255,
            optimize=True,
        )
        return output.getvalue()
    finally:
        for frame in frames:
            frame.close()


def _timeline(
    animations: Sequence[_Animation], duration: int, max_frames: int
) -> list[int]:
    changes = {0}
    for animation in animations:
        cycle = 0
        while cycle < duration:
            changes.update(
                cycle + start
                for start in animation.starts
                if cycle + start < duration
            )
            cycle += animation.duration
    ordered = sorted(changes)
    if len(ordered) <= max_frames:
        return ordered
    return sorted(
        {
            ordered[round(index * (len(ordered) - 1) / (max_frames - 1))]
            for index in range(max_frames)
        }
    )
