from __future__ import annotations

import asyncio
from io import BytesIO
from typing import TYPE_CHECKING

import httpx
import pytest
from PIL import Image

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


def _png(width: int, height: int, color: tuple[int, int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (width, height), color).save(output, format="PNG")
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
    assert [result.getpixel((x, 200)) for x in (50, 150, 250, 350)] == list(
        colors
    )


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
