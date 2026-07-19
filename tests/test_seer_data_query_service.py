from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.config.models.seer import SeasonCountdownConfig
from ironsbot.services.seer.data_queries import SeerDataQueryService
from ironsbot.services.seer.images import ImageSourceError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource


class FakeData:
    def __init__(self, value: Any) -> None:
        self.value = value

    @contextmanager
    def query(self, _operation: object) -> Iterator[Any]:
        yield self.value


class FakeImages:
    def __init__(self, *, fail_url: bool = False) -> None:
        self.fail_url = fail_url

    async def fetch_url(self, _url: str) -> bytes:
        if self.fail_url:
            raise ImageSourceError("unavailable")
        return b"remote"

    async def fetch(
        self,
        _kind: object,
        _key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        assert fallback is False
        return b"fallback"


def _service(value: Any, *, fail_url: bool = False) -> SeerDataQueryService:
    return SeerDataQueryService(
        cast("SeerDataAccess", FakeData(value)),
        cast("SeerImageSource", FakeImages(fail_url=fail_url)),
        SeasonCountdownConfig(),
    )


@pytest.mark.asyncio
async def test_data_version_normalizes_utc_to_china_time() -> None:
    service = _service(datetime(2026, 7, 19, 1, 2, 3, tzinfo=timezone.utc))

    assert await service.data_version() == "数据更新时间：2026-07-19 09:02:03"


@pytest.mark.asyncio
async def test_weekly_preview_uses_remote_image() -> None:
    service = _service(("https://example.com/preview.png", "source"))

    assert await service.weekly_preview() == b"remote"


@pytest.mark.asyncio
async def test_weekly_preview_falls_back_to_packaged_image() -> None:
    service = _service(
        ("https://example.com/preview.png", "source"),
        fail_url=True,
    )

    assert await service.weekly_preview() == b"fallback"
