from __future__ import annotations

import asyncio
from io import BytesIO
from threading import Event
from typing import TYPE_CHECKING

import httpx
import pytest
from PIL import Image, ImageDraw

from ironsbot.integrations import animated_collage
from ironsbot.integrations.animated_collage import (
    MAX_OUTPUT_BYTES,
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
MAX_COMBINED_ANIMATION_FRAMES = 100
MAX_COMBINED_ANIMATION_DURATION_MS = 10_000
MIN_QUALITY_WIDTH = 480


@pytest.mark.asyncio
async def test_prepare_bytes_shares_original_fallback_and_does_not_download() -> None:
    async def fetch(_url: str, _limit: int) -> bytes:
        raise AssertionError

    def fail(_images: Sequence[bytes], **_limits: int) -> bytes:
        raise ImageCollageError.render_failed()

    sources = (b"first", b"second", b"third")
    service = ImageCollageService(fetch, fail)
    assert await service.prepare_bytes(()) == ()
    assert (
        tuple(image.content for image in await service.prepare_bytes(sources))
        == sources
    )
    assert (await service.prepare_bytes((b"single",)))[0].content == b"single"


@pytest.mark.asyncio
async def test_prepare_bytes_combines_three_images() -> None:
    async def fetch(_url: str, _limit: int) -> bytes:
        raise AssertionError

    service = ImageCollageService(fetch, render_adaptive_collage)
    sources = tuple(_png(10, 10, (value, 0, 0, 255)) for value in (10, 20, 30))
    output = await service.prepare_bytes(sources)
    assert len(output) == 1
    assert output[0].content is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("bug"), asyncio.CancelledError()])
async def test_prepare_bytes_does_not_swallow_unexpected_errors(
    error: BaseException,
) -> None:
    async def fetch(_url: str, _limit: int) -> bytes:
        raise AssertionError

    def fail(_images: Sequence[bytes], **_limits: int) -> bytes:
        raise error

    with pytest.raises(type(error)):
        await ImageCollageService(fetch, fail).prepare_bytes((b"one", b"two"))


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


def test_four_portrait_images_use_filled_two_by_two_layout() -> None:
    # Same aspect ratio as dynamic 1255164680735817733 (900 x 1300).
    colors = (
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
        (255, 255, 0, 255),
    )
    with _render([_png(90, 130, color) for color in colors]) as result:
        assert result.size == (180, 260)
        assert [
            result.getpixel(position)
            for position in ((45, 65), (135, 65), (45, 195), (135, 195))
        ] == list(colors)
        assert result.getchannel("A").getextrema() == (255, 255)


def test_collage_is_scaled_as_a_whole_to_output_limit() -> None:
    images = [_png(100, 400, (255, 0, 0, 255)) for _index in range(4)]
    result = _render(images, max_side=200)

    assert result.size == (200, 200)


def test_small_image_and_large_images_fill_the_entire_canvas() -> None:
    colors = ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255))
    images = [_png(100, 100, color) for color in colors]
    images.append(_png(20, 10, (255, 255, 0, 255)))
    with _render(images) as result:
        assert result.getchannel("A").getextrema() == (255, 255)
        palette = result.getcolors()
        assert palette is not None
        counts = {color: count for count, color in palette}
        assert set(counts) == {*colors, (255, 255, 0, 255)}



def test_small_image_can_upscale_beyond_two_times_without_padding() -> None:
    images = [_png(20, 10, (255, 0, 0, 255)), _png(82, 41, (0, 0, 255, 255))]
    with _render(images) as result:
        assert result.getchannel("A").getextrema() == (255, 255)
        red_pixels = result.getchannel("R").histogram()[255]
        assert red_pixels > 20 * 10 * 4



def test_same_height_narrow_image_does_not_add_row_padding() -> None:
    images = [_png(100, 100, (255, 0, 0, 255)) for _index in range(3)]
    images.append(_png(40, 100, (0, 0, 255, 255)))
    with _render(images) as result:
        assert result.size == (340, 100)
        assert result.getchannel("A").getextrema() == (255, 255)



@pytest.mark.parametrize(
    "sizes",
    [
        [(90, 130)] * 4,
        [(100, 400)] * 4,
        [(20, 20)] * 3,
        [(20, 20), (20, 20), (20, 40)],
        [(200, 20)] * 2,
        [(1280, 854), (720, 6000)],
        [(701, 503), (37, 99), (301, 401), (127, 43), (61, 233)],
    ],
)
def test_mixed_sizes_have_no_layout_whitespace_and_keep_reading_order(
    sizes: Sequence[tuple[int, int]],
) -> None:
    colors = [(index * 30, 10, 20, 255) for index in range(len(sizes))]
    with _render(
        [_png(w, h, c) for (w, h), c in zip(sizes, colors, strict=True)]
    ) as result:
        assert result.getchannel("A").getextrema() == (255, 255)
        pixels = result.load()
        assert pixels is not None
        first_positions = [
            next(
                (y, x)
                for y in range(result.height)
                for x in range(result.width)
                if pixels[x, y] == color
            )
            for color in colors
        ]
        assert first_positions == sorted(first_positions)



def test_transparency_is_preserved_inside_images() -> None:
    images = [_png(20, 20, (255, 0, 0, 128)) for _index in range(4)]
    with _render(images) as result:
        assert result.size == (40, 40)
        assert result.getpixel((10, 10)) == (255, 0, 0, 128)
        assert result.getchannel("A").getextrema() == (128, 128)


def test_pixel_limit_scales_selected_layout_without_reflowing() -> None:
    pixel_limit = 35_000
    images = [_png(100, 100, (255, 0, 0, 255)) for _index in range(3)]
    images.append(_png(20, 10, (0, 0, 255, 255)))
    content = render_adaptive_collage(images, max_side=MAX_SIDE, max_pixels=pixel_limit)
    with Image.open(BytesIO(content)) as result:
        assert result.width * result.height <= pixel_limit
        assert result.getchannel("A").getextrema() == (255, 255)



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
    assert len(result) <= MAX_OUTPUT_BYTES

    with Image.open(BytesIO(result)) as image:
        assert bool(getattr(image, "is_animated", False))
        assert int(getattr(image, "n_frames", 1)) >= EXPECTED_ANIMATION_FRAMES
        assert image.size == (40, 100)
        image.seek(0)
        rgba = image.convert("RGBA")
        assert rgba.getpixel((20, 10)) == (255, 0, 0, 255)
        assert rgba.getpixel((20, 40)) == (0, 0, 255, 255)
        assert rgba.getpixel((5, 40)) == (0, 0, 255, 255)


def test_animated_collage_uses_qq_thumbnail_width_for_wide_gifs() -> None:
    expected_size = (720, 194)
    result = render_vertical_animation(
        (
            _gif(1000, 120, ((255, 0, 0, 255), (0, 255, 0, 255))),
            _gif(800, 120, ((0, 0, 255, 255), (255, 255, 0, 255))),
        )
    )

    with Image.open(BytesIO(result)) as image:
        assert image.size == expected_size
    assert len(result) <= MAX_OUTPUT_BYTES


def test_animated_collage_caps_duration_and_frame_count() -> None:
    colors = tuple(
        ((index * 31) % 256, (index * 47) % 256, (index * 67) % 256, 255)
        for index in range(120)
    )
    result = render_vertical_animation(
        (
            _gif(2, 2, colors, duration=100),
            _gif(2, 2, tuple(reversed(colors)), duration=100),
        )
    )

    with Image.open(BytesIO(result)) as image:
        frame_count = int(getattr(image, "n_frames", 1))
        durations = []
        for index in range(frame_count):
            image.seek(index)
            durations.append(int(image.info.get("duration", 0)))
        assert frame_count <= MAX_COMBINED_ANIMATION_FRAMES
        assert sum(durations) <= MAX_COMBINED_ANIMATION_DURATION_MS
        assert image.info.get("loop") == 0


def test_animated_collage_uses_the_full_quality_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_widths: list[int] = []

    def fake_render(
        _animations: Sequence[object],
        *,
        max_width: int,
        max_height: int,
        max_pixels: int,
        max_frames: int,
        colors: int,
    ) -> bytes:
        del max_height, max_pixels, max_frames, colors
        attempted_widths.append(max_width)
        return b"fits" if max_width == MIN_QUALITY_WIDTH else b"too-large"

    monkeypatch.setattr(animated_collage, "MAX_OUTPUT_BYTES", len(b"fits"))
    monkeypatch.setattr(animated_collage, "_render_quality", fake_render)

    result = render_vertical_animation(
        (
            _gif(2, 2, ((255, 0, 0, 255), (0, 255, 0, 255))),
            _gif(2, 2, ((0, 0, 255, 255), (255, 255, 0, 255))),
        )
    )

    assert result == b"fits"
    assert attempted_widths == [720, MIN_QUALITY_WIDTH]


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
    outputs = await service.prepare_urls(("static-1", "static-2", "gif-1", "gif-2"))

    assert len(outputs) == EXPECTED_MEDIA_GROUPS
    assert outputs[0].content_type == "image/png"
    assert outputs[0].content is not None
    assert outputs[1].content_type == "image/gif"
    assert outputs[1].content is not None
    assert inspect_animation(outputs[1].content)


@pytest.mark.asyncio
async def test_service_streams_completed_media_groups_without_waiting_for_slowest() -> (
    None
):
    static_ready = Event()
    release_animation = Event()

    async def fetch(url: str, _max_bytes: int) -> bytes:
        if url == "static-1":
            return _png(10, 10, (255, 0, 0, 255))
        if url == "static-2":
            return _png(10, 10, (0, 255, 0, 255))
        if url == "gif-1":
            return _gif(10, 10, ((0, 0, 255, 255), (255, 255, 0, 255)))
        return _gif(10, 10, ((255, 0, 255, 255), (0, 255, 255, 255)))

    def render_static(
        image_bytes: Sequence[bytes], *, max_side: int, max_pixels: int
    ) -> bytes:
        del image_bytes, max_side, max_pixels
        static_ready.set()
        return b"static-result"

    def wait_animation(image_bytes: Sequence[bytes]) -> bytes:
        del image_bytes
        release_animation.wait(timeout=5)
        return b"animation-result"

    service = ImageCollageService(
        fetch,
        render_static,
        render_animation=wait_animation,
        inspect_animation=inspect_animation,
    )
    stream = service.iter_prepared_urls(("static-1", "static-2", "gif-1", "gif-2"))
    first = await anext(stream)

    assert static_ready.is_set()
    assert first.content == b"static-result"
    release_animation.set()
    second = await anext(stream)
    assert second.content == b"animation-result"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


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
async def test_media_limit_is_applied_to_each_consecutive_group() -> None:
    static_urls = tuple(f"static-{index}" for index in range(10))
    animated_urls = tuple(f"animated-{index}" for index in range(10))

    async def fetch(url: str, _max_bytes: int) -> bytes:
        index = int(url.rsplit("-", 1)[1])
        colors = (
            ((index * 19) % 256, 0, 0, 255),
            (0, (index * 23 + 1) % 256, 0, 255),
        )
        return (
            _gif(2, 2, colors) if url.startswith("animated") else _png(2, 2, colors[0])
        )

    service = ImageCollageService(
        fetch,
        lambda image_bytes, **_kwargs: b"static:" + b"|".join(image_bytes),
        render_animation=lambda image_bytes: b"animated:" + b"|".join(image_bytes),
        inspect_animation=inspect_animation,
        max_images=18,
    )
    outputs = await service.prepare_urls((*static_urls, *animated_urls))

    assert len(outputs) == EXPECTED_MEDIA_GROUPS
    assert outputs[0].content_type == "image/png"
    assert outputs[1].content_type == "image/gif"


@pytest.mark.asyncio
async def test_oversized_consecutive_group_falls_back_to_original_media() -> None:
    urls = tuple(f"animated-{index}" for index in range(19))

    async def fetch(url: str, _max_bytes: int) -> bytes:
        return b"animated:" + url.encode()

    def unexpected_render(image_bytes: Sequence[bytes]) -> bytes:
        del image_bytes
        raise AssertionError

    service = ImageCollageService(
        fetch,
        render_adaptive_collage,
        render_animation=unexpected_render,
        inspect_animation=lambda image_bytes: image_bytes.startswith(b"animated:"),
        max_images=18,
    )
    outputs = await service.prepare_urls(urls)

    assert tuple(output.url for output in outputs) == urls


@pytest.mark.asyncio
async def test_service_preserves_failed_url_without_blocking_other_collage() -> None:
    async def fetch(url: str, _max_bytes: int) -> bytes:
        if url == "failed":
            raise ImageCollageError.download_failed()
        return (
            _png(10, 10, (255, 0, 0, 255))
            if url == "one"
            else _png(10, 10, (0, 0, 255, 255))
        )

    service = ImageCollageService(
        fetch,
        render_adaptive_collage,
        inspect_animation=inspect_animation,
    )
    outputs = await service.prepare_urls(("one", "failed", "two"))

    assert [output.url for output in outputs] == ["one", "failed", "two"]


@pytest.mark.asyncio
async def test_small_portrait_detail_fills_collage_beside_large_cover() -> None:
    sources = (
        _png(1280, 854, (255, 0, 0, 255)),
        _png(120, 213, (0, 0, 255, 255)),
    )

    async def fetch(url: str, _limit: int) -> bytes:
        return sources[int(url)]

    service = ImageCollageService(fetch, render_adaptive_collage)
    prepared_bytes = await service.prepare_bytes(sources)
    assert len(prepared_bytes) == 1
    assert prepared_bytes[0].content is not None
    with Image.open(BytesIO(prepared_bytes[0].content)) as result:
        assert result.getchannel("A").getextrema() == (255, 255)
        assert result.width * result.height >= 1_000_000  # noqa: PLR2004
    prepared_urls = await service.prepare_urls(("0", "1"))
    assert len(prepared_urls) == 1
    assert prepared_urls[0].content == prepared_bytes[0].content



def test_all_four_source_corners_survive_without_cropping() -> None:
    output = BytesIO()
    with Image.new("RGBA", (100, 100), "white") as source:
        draw = ImageDraw.Draw(source)
        for box, color in (
            ((0, 0, 19, 19), "red"),
            ((80, 0, 99, 19), "green"),
            ((0, 80, 19, 99), "blue"),
            ((80, 80, 99, 99), "black"),
        ):
            draw.rectangle(box, fill=color)
        source.save(output, format="PNG")
    with _render([output.getvalue()] * 2) as result:
        assert result.size == (100, 200)
        for offset in (0, 100):
            assert result.getpixel((5, offset + 5)) == (255, 0, 0, 255)
            assert result.getpixel((95, offset + 5)) == (0, 128, 0, 255)
            assert result.getpixel((5, offset + 95)) == (0, 0, 255, 255)
            assert result.getpixel((95, offset + 95)) == (0, 0, 0, 255)

