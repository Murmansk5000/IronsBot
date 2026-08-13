from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.config.models.seer import SeasonCountdownConfig
from ironsbot.services.seer.data_queries import (
    DataQueryImageReply,
    SeerDataQueryService,
)
from ironsbot.services.seer.weekly_preview_images import (
    WeeklyPreviewImage,
    WeeklyPreviewImageError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.new_content import NewContentService
    from ironsbot.services.seer.weekly_preview_images import WeeklyPreviewImageSource


class FakeNewContent:
    def snapshot(self) -> object:
        return object()


class FakeData:
    def __init__(self, value: Any) -> None:
        self.value = value

    @contextmanager
    def query(self, _operation: object) -> Iterator[Any]:
        yield self.value


PREVIEW_TIME = datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)


class FakePreviewImages:
    def __init__(self, *, stale: bool = False, fail: bool = False) -> None:
        self.stale = stale
        self.fail = fail

    async def fetch(self, _url: str) -> WeeklyPreviewImage:
        if self.fail:
            error = WeeklyPreviewImageError.from_detail("primary: ConnectError")
            raise error
        return WeeklyPreviewImage(
            b"remote",
            PREVIEW_TIME,
            "https://example.com/preview.png",
            stale=self.stale,
        )


def _service(
    value: Any,
    *,
    stale: bool = False,
    fail: bool = False,
) -> SeerDataQueryService:
    return SeerDataQueryService(
        cast("SeerDataAccess", FakeData(value)),
        cast(
            "WeeklyPreviewImageSource",
            FakePreviewImages(stale=stale, fail=fail),
        ),
        SeasonCountdownConfig(),
        cast("NewContentService", FakeNewContent()),
    )


@pytest.mark.asyncio
async def test_data_version_normalizes_utc_to_china_time() -> None:
    service = _service(datetime(2026, 7, 19, 1, 2, 3, tzinfo=timezone.utc))

    assert await service.data_version() == "数据更新时间：2026-07-19 09:02:03"


@pytest.mark.asyncio
async def test_weekly_preview_uses_remote_image() -> None:
    service = _service(("https://example.com/preview.png", "source"))

    assert await service.weekly_preview() == DataQueryImageReply(b"remote")


@pytest.mark.asyncio
async def test_weekly_preview_marks_stale_cache_time() -> None:
    service = _service(
        ("https://example.com/preview.png", "source"),
        stale=True,
    )

    assert await service.weekly_preview() == DataQueryImageReply(
        b"remote",
        "⚠️ 网络刷新失败，当前为缓存图片；缓存时间：2026-08-10 11:00:00",
    )


@pytest.mark.asyncio
async def test_weekly_preview_reports_source_failure() -> None:
    service = _service(
        ("https://example.com/preview.png", "source"),
        fail=True,
    )

    assert await service.weekly_preview() == (
        "❌获取图片失败！原因：primary: ConnectError"
    )
