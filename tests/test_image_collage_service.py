from __future__ import annotations

import asyncio
from io import BytesIO
from typing import TYPE_CHECKING

import httpx
import pytest
from PIL import Image

from ironsbot.integrations.animated_collage import (
    inspect_animation,
    render_vertical_animation,
)
from ironsbot.integrations.image_collage import (
    fetch_collage_image,
    render_adaptive_collage,
)
from ironsbot.services.messaging.image_collage import (
    ImageCollageError,
    ImageCollageService,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

MAX_SIDE = 12_000
MAX_PIXELS = 40_000_000
TEST_DOWNLOAD_CONCURRENCY = 2
EXPECTED_ANIMATION_FRAMES = 2
EXPECTED_MEDIA_GROUPS = 2


def _png(width: int, height: int, color: tuple[int, int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (width, height), color).save(output, format="PNG")
    return output.getvalue()


def _gif(
    width: int,
    height: int,
    colors: Sequence[tuple[int, int, int, int]],
    *,
    duration: int = 100,
) -> bytes:
    output = BytesIO()
    frames = [Image.new("RGBA", (width, height), color) for color in colors]
    try:
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=0,
            disposal=2,
        )
    finally:
        for frame in frames:
            frame.close()
    return output.getvalue()


def _render(images: Sequence[bytes], *, max_side: int = MAX_SIDE) -> Image.Image:
    data = render_adaptive_collage(
        images,
        max_side=max_side,
        max_pixels=MAX_PIXELS,
    )
    with Image.open(BytesIO(data)) as result:
        result.load()
        return result.copy()


def test_four_tall_images_are_joined_in_one_ordered_row() -> None:
    colors = (
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
        (255, 255, 0, 255),
    )
    result = _render([_png(100, 400, color) for color in colors])

    assert result.size == (400, 400)
    assert [result.getpixel((x, 200)) for x in (50, 150, 250, 350)] == list(colors)


def test_four_square_images_use_two_by_two_layout() -> None:
    images = [_png(100, 100, (index * 40, 0, 0, 255)) for index in range(4)]
    result = _render(images)

    assert result.size == (200, 200)


def test_collage_is_scaled_as_a_whole_to_output_limit() -> None:
    images = [_png(100, 400, (255, 0, 0, 255)) for _index in range(4)]
    result = _render(images, max_side=200)

    assert result.size == (200, 200)


def test_animated_image_rejects_the_complete_collage() -> None:
    output = BytesIO()
    frames = [
        Image.new("RGB", (10, 10), (255, 0, 0)),
        Image.new("RGB", (10, 10), (0, 255, 0)),
    ]
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )

    with pytest.raises(ImageCollageError, match="animated"):
        _render([output.getvalue(), _png(10, 10, (0, 0, 255, 255))])


@pytest.mark.asyncio
async def test_service_downloads_in_input_order() -> None:
    fetched: list[str] = []
    rendered: list[bytes] = []

    async def fetch(url: str, _max_bytes: int) -> bytes:
        fetched.append(url)
        await asyncio.sleep(0)
        return url.encode()

    def render(
        image_bytes: Sequence[bytes],
        *,
        max_side: int,
        max_pixels: int,
    ) -> bytes:
        assert max_side == MAX_SIDE
        assert max_pixels == MAX_PIXELS
        rendered.extend(image_bytes)
        return b"collage"

    service = ImageCollageService(fetch, render)
    result = await service.compose_urls(("one", "two", "three"))

    assert result == b"collage"
    assert set(fetched) == {"one", "two", "three"}
    assert rendered == [b"one", b"two", b"three"]


@pytest.mark.asyncio
async def test_service_limits_parallel_image_downloads() -> None:
    active = 0
    peak = 0

    async def fetch(url: str, _max_bytes: int) -> bytes:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return url.encode()

    def render(
        image_bytes: Sequence[bytes],
        *,
        max_side: int,
        max_pixels: int,
    ) -> bytes:
        assert max_side == MAX_SIDE
        assert max_pixels == MAX_PIXELS
        assert image_bytes
        return b"collage"

    service = ImageCollageService(
        fetch,
        render,
        download_concurrency=TEST_DOWNLOAD_CONCURRENCY,
    )
    await service.compose_urls(tuple(str(index) for index in range(6)))

    assert peak == TEST_DOWNLOAD_CONCURRENCY


@pytest.mark.asyncio
async def test_http_image_fetch_rejects_non_image_response() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"not an image",
            )
        )
    ) as client:
        with pytest.raises(ImageCollageError, match="content type"):
            await fetch_collage_image(client, "https://example.test/image", 100)


def test_animated_collage_stacks_rows_without_changing_aspect_ratio() -> None:
    result = render_vertical_animation(
        (
            _gif(40, 20, ((255, 0, 0, 255), (0, 255, 0, 255))),
            _gif(20, 40, ((0, 0, 255, 255), (255, 255, 0, 255))),
        )
    )

    with Image.open(BytesIO(result)) as image:
        assert bool(getattr(image, "is_animated", False))
        assert int(getattr(image, "n_frames", 1)) >= EXPECTED_ANIMATION_FRAMES
        assert image.size == (40, 60)
        image.seek(0)
        rgba = image.convert("RGBA")
        assert rgba.getpixel((20, 10)) == (255, 0, 0, 255)
        assert rgba.getpixel((20, 40)) == (0, 0, 255, 255)
        assert rgba.getchannel("A").getpixel((5, 40)) == 0


@pytest.mark.asyncio
async def test_service_groups_consecutive_static_and_animated_images() -> None:
    content = {
        "static-1": _png(10, 10, (255, 0, 0, 255)),
        "static-2": _png(10, 10, (0, 255, 0, 255)),
        "gif-1": _gif(10, 10, ((255, 0, 0, 255), (0, 255, 0, 255))),
        "gif-2": _gif(10, 20, ((0, 0, 255, 255), (255, 255, 0, 255))),
    }

    async def fetch(url: str, _max_bytes: int) -> bytes:
        return content[url]

    service = ImageCollageService(
        fetch,
        render_adaptive_collage,
        render_animation=render_vertical_animation,
        inspect_animation=inspect_animation,
    )
    outputs = await service.prepare_urls(
        ("static-1", "static-2", "gif-1", "gif-2")
    )

    assert len(outputs) == EXPECTED_MEDIA_GROUPS
    assert outputs[0].content_type == "image/png"
    assert outputs[0].content is not None
    assert outputs[1].content_type == "image/gif"
    assert outputs[1].content is not None
    assert inspect_animation(outputs[1].content)


@pytest.mark.asyncio
async def test_service_deduplicates_urls_and_identical_content() -> None:
    shared = _png(10, 10, (255, 0, 0, 255))

    async def fetch(url: str, _max_bytes: int) -> bytes:
        return shared if url != "unique" else _png(10, 10, (0, 0, 255, 255))

    service = ImageCollageService(
        fetch,
        render_adaptive_collage,
        inspect_animation=inspect_animation,
    )
    outputs = await service.prepare_urls(("same", "same", "copy", "unique"))

    assert len(outputs) == 1
    assert outputs[0].content is not None


@pytest.mark.asyncio
async def test_service_preserves_failed_url_without_blocking_other_collage() -> None:
    async def fetch(url: str, _max_bytes: int) -> bytes:
        if url == "failed":
            raise ImageCollageError.download_failed()
        return _png(10, 10, (255, 0, 0, 255)) if url == "one" else _png(
            10, 10, (0, 0, 255, 255)
        )

    service = ImageCollageService(
        fetch,
        render_adaptive_collage,
        inspect_animation=inspect_animation,
    )
    outputs = await service.prepare_urls(("one", "failed", "two"))

    assert [output.url for output in outputs] == ["one", "failed", "two"]
