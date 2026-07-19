from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.core import time
from ironsbot.services.operations.headless_errors import DisconnectedError
from ironsbot.services.seer.peak import (
    PeakItemData,
    PeakQueryService,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest import MonkeyPatch

    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.peak import (
        PeakPetRenderer,
        PeakPoolRenderer,
        PeakVoteRenderer,
    )


class FakeData:
    suit = object()
    title = object()
    pet = object()

    def __init__(self) -> None:
        self.query_result: Any = None
        self.models: dict[int, Any] = {}

    @contextmanager
    def query(self, _operation: object) -> Iterator[Any]:
        yield self.query_result

    @contextmanager
    def get_many(
        self,
        _getter: object,
        _ids: set[int],
    ) -> Iterator[dict[int, Any]]:
        yield self.models


class FakeHeadless:
    def __init__(self, game: Any = None, error: Exception | None = None) -> None:
        self.game = game
        self.error = error

    def get_game(self) -> Any:
        if self.error is not None:
            raise self.error
        return self.game


def _service(
    data: FakeData,
    headless: FakeHeadless,
    rendered: dict[str, Any],
) -> PeakQueryService:
    async def render_pool(pools: Any, title: str) -> bytes:
        rendered["pool"] = (pools, title)
        return b"pool"

    async def render_vote(pools: Any) -> bytes:
        rendered["vote"] = pools
        return b"vote"

    async def render_pet(**kwargs: Any) -> bytes:
        rendered["pet"] = kwargs
        return b"pet"

    return PeakQueryService(
        cast("SeerDataAccess", data),
        cast("HeadlessService", headless),
        cast("PeakPoolRenderer", render_pool),
        cast("PeakVoteRenderer", render_vote),
        cast("PeakPetRenderer", render_pet),
    )


@pytest.mark.asyncio
async def test_peak_pool_query_renders_with_progress() -> None:
    data = FakeData()
    data.query_result = (
        SimpleNamespace(
            start_time=datetime(2026, 7, 1, tzinfo=time.TZ_CN),
            end_time=datetime(2026, 7, 31, tzinfo=time.TZ_CN),
        ),
    )
    rendered: dict[str, Any] = {}
    progress: list[str] = []

    async def report(message: str) -> None:
        progress.append(message)

    result = await _service(data, FakeHeadless(), rendered).pool(
        expert=False,
        progress=report,
    )

    assert result.image == b"pool"
    assert progress == ["正在生成图片..."]
    assert rendered["pool"][1] == "竞技池 / 2026-07-01 ~ 2026-07-31"


@pytest.mark.asyncio
async def test_peak_query_reports_disconnected_headless_client() -> None:
    service = _service(
        FakeData(),
        FakeHeadless(error=DisconnectedError()),
        {},
    )

    result = await service.item_rank("竞技套装榜", kind="套装")

    assert result.message == (
        "❌ 无头客户端连接已断开，正在尝试重连，请稍后再试"
    )


@pytest.mark.asyncio
async def test_peak_item_rank_formats_game_results(
    monkeypatch: MonkeyPatch,
) -> None:
    data = FakeData()
    data.query_result = SimpleNamespace(sub_key=1)
    data.models = {7: SimpleNamespace(name="勇者套装")}

    class FakeGame:
        async def get_peak_suit_rank(
            self,
            _sub_key: int,
            _peak_type: object,
        ) -> list[PeakItemData]:
            return [PeakItemData(id=7, count=10, win=6)]

    now = datetime(2026, 7, 19, 12, 0, tzinfo=time.TZ_CN)
    monkeypatch.setattr(time, "now", lambda *, tz: now.astimezone(tz))
    result = await _service(
        data,
        FakeHeadless(FakeGame()),
        {},
    ).item_rank("竞技套装榜", kind="套装")

    assert result.text == (
        "竞技套装榜（截至2026-07-19 12:00:00）\n"
        "1. 勇者套装 | 出场 10 | 胜场 6 | 胜率 60.0%"
    )
