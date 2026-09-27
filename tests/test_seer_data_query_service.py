from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.config.models.seer import SeasonCountdownConfig
from ironsbot.services.messaging.image_collage import (
    ImageCollageError,
    ImageCollageService,
)
from ironsbot.services.seer.data_queries import (
    DataQueryImageReply,
    SeerDataQueryService,
)
from ironsbot.services.seer.data_query_facts import WeeklyPreviewLinks
from ironsbot.services.seer.weekly_preview_images import (
    WeeklyPreviewImage,
    WeeklyPreviewImageError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.services.seer.data_query_facts import (
        PeakSeasonTimes,
        SeerDataQueryFacts,
    )
    from ironsbot.services.seer.new_content import NewContentService
    from ironsbot.services.seer.weekly_preview_images import WeeklyPreviewImageSource


class FakeNewContent:
    def snapshot(self) -> object:
        return object()


class FakeFacts:
    def __init__(self, value: Any) -> None:
        self.value = value

    def weekly_preview_links(self) -> WeeklyPreviewLinks:
        return WeeklyPreviewLinks(*self.value)

    def generated_at(self) -> datetime | None:
        return cast("datetime | None", self.value)

    def peak_season_times(self) -> PeakSeasonTimes | None:
        return cast("PeakSeasonTimes | None", self.value)


PREVIEW_TIME = datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)


class FakePreviewImages:
    def __init__(
        self,
        *,
        stale: bool = False,
        fail: bool = False,
        fail_urls: frozenset[str] = frozenset(),
    ) -> None:
        self.stale = stale
        self.fail = fail
        self.fail_urls = fail_urls

    async def fetch(self, url: str) -> WeeklyPreviewImage:
        if self.fail or url in self.fail_urls:
            error = WeeklyPreviewImageError.from_detail("primary: ConnectError")
            raise error
        return WeeklyPreviewImage(
            url.encode(),
            PREVIEW_TIME,
            url,
            stale=self.stale,
        )


def _service(
    value: Any,
    *,
    stale: bool = False,
    fail: bool = False,
    fail_urls: frozenset[str] = frozenset(),
    image_collage: ImageCollageService | None = None,
) -> SeerDataQueryService:
    return SeerDataQueryService(
        cast("SeerDataQueryFacts", FakeFacts(value)),
        cast(
            "WeeklyPreviewImageSource",
            FakePreviewImages(
                stale=stale,
                fail=fail,
                fail_urls=fail_urls,
            ),
        ),
        SeasonCountdownConfig(),
        cast("NewContentService", FakeNewContent()),
        image_collage=image_collage,
    )


@pytest.mark.asyncio
async def test_data_version_normalizes_utc_to_china_time() -> None:
    service = _service(datetime(2026, 7, 19, 1, 2, 3, tzinfo=timezone.utc))

    assert await service.data_version() == "数据更新时间：2026-07-19 09:02:03"


@pytest.mark.asyncio
async def test_weekly_preview_uses_remote_image() -> None:
    first = "https://example.com/preview.png"
    second = "https://example.com/imgPreview_1.png"
    service = _service(((first, second), "https://example.com/source"))

    assert await service.weekly_preview() == DataQueryImageReply(
        first.encode(),
        additional_images=(second.encode(),),
        source_url="https://example.com/source",
    )


@pytest.mark.asyncio
async def test_weekly_preview_combines_two_images_with_shared_collage() -> None:
    first = "https://example.com/preview.png"
    second = "https://example.com/imgPreview_1.png"

    async def unused_fetch(_url: str, _max_bytes: int) -> bytes:
        raise AssertionError

    def render(
        image_bytes: Sequence[bytes], *, max_side: int, max_pixels: int
    ) -> bytes:
        assert image_bytes == (first.encode(), second.encode())
        assert max_side > 0 and max_pixels > 0
        return b"combined"

    service = _service(
        ((first, second), "https://example.com/source"),
        image_collage=ImageCollageService(unused_fetch, render),
    )

    assert await service.weekly_preview() == DataQueryImageReply(
        b"combined", source_url="https://example.com/source"
    )


@pytest.mark.asyncio
async def test_weekly_preview_keeps_originals_if_collage_fails() -> None:
    first = "https://example.com/preview.png"
    second = "https://example.com/imgPreview_1.png"

    async def unused_fetch(_url: str, _max_bytes: int) -> bytes:
        raise AssertionError

    def failed_render(
        image_bytes: Sequence[bytes], *, max_side: int, max_pixels: int
    ) -> bytes:
        del image_bytes, max_side, max_pixels
        raise ImageCollageError.render_failed()

    service = _service(
        ((first, second), "source"),
        image_collage=ImageCollageService(unused_fetch, failed_render),
    )

    assert await service.weekly_preview() == DataQueryImageReply(
        first.encode(),
        additional_images=(second.encode(),),
        source_url="source",
    )


@pytest.mark.asyncio
async def test_weekly_preview_marks_stale_cache_time() -> None:
    service = _service(
        (("https://example.com/preview.png",), "source"),
        stale=True,
    )

    assert await service.weekly_preview() == DataQueryImageReply(
        b"https://example.com/preview.png",
        "⚠️ 网络刷新失败，当前为缓存图片；缓存时间：2026-08-10 11:00:00",
        source_url="source",
    )


@pytest.mark.asyncio
async def test_weekly_preview_reports_source_failure() -> None:
    service = _service(
        (("https://example.com/preview.png",), "source"),
        fail=True,
    )

    assert await service.weekly_preview() == "图片素材获取失败，暂时无法显示。"


@pytest.mark.asyncio
async def test_weekly_preview_keeps_available_images_after_partial_failure() -> None:
    first = "https://example.com/preview.png"
    second = "https://example.com/imgPreview_1.png"
    service = _service(
        ((first, second), "source"),
        fail_urls=frozenset({second}),
    )

    assert await service.weekly_preview() == DataQueryImageReply(
        first.encode(),
        "⚠️ 部分预告图片获取失败，已显示可用图片。",
        source_url="source",
    )
