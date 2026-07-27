from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.services.seer.local_rank_models import LocalRankCacheStats
from ironsbot.services.seer.rank_admin import (
    RankAdminPolicy,
    RankAdminService,
)
from ironsbot.services.seer.rank_list_models import RankListCommand, RankPlayerCommand
from ironsbot.services.seer.rank_queries import (
    RankQueryPolicy,
    RankQueryService,
)

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.rank import RankService
    from ironsbot.services.seer.rank_display import RankDisplayService
    from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService


class FakeRank:
    @staticmethod
    def current_peak_sub_key() -> None:
        return None


class FakeLocalRank:
    def __init__(self) -> None:
        self.cache_stats = LocalRankCacheStats(0, 0, 100, {})

    @staticmethod
    def entries(
        _metric_key: str,
        **_kwargs: Any,
    ) -> tuple[list[Any], int]:
        return [], 0

    def stats(self) -> LocalRankCacheStats:
        return self.cache_stats


class FakeDisplay:
    config = SimpleNamespace(max_display_limit=50)

    def __init__(self) -> None:
        self.saved: tuple[int, int, int] | None = None

    @staticmethod
    def limit_for_group(_group_id: int | None) -> int:
        return 20

    def set_group_limit(
        self,
        group_id: int,
        user_id: int,
        limit: int,
    ) -> None:
        self.saved = group_id, user_id, limit


class NoHeadlessAccess:
    @staticmethod
    def get_game() -> None:
        pytest.fail("local rank query must not require headless")


def _query_service(
    local_rank: FakeLocalRank,
    display: FakeDisplay,
) -> RankQueryService:
    return RankQueryService(
        cast("RankService", FakeRank()),
        cast("LocalRankService", local_rank),
        cast("RankDisplayService", display),
        cast("HeadlessService", NoHeadlessAccess()),
        RankQueryPolicy(
            player_error=lambda _player_id, error: str(error),
            player_timeout_seconds=5,
        ),
    )


@pytest.mark.asyncio
async def test_local_rank_query_does_not_require_headless_client() -> None:
    message = await _query_service(
        FakeLocalRank(),
        FakeDisplay(),
    ).list(
        RankListCommand(
            kind="local",
            rank_key="图鉴积分",
            start_rank=1,
            limit=20,
        )
    )

    assert "样本图鉴积分榜" in message
    assert "先查询一些米米号后再试" in message


@pytest.mark.asyncio
async def test_rank_player_query_rejects_invalid_player_id_before_headless() -> None:
    message = await _query_service(
        FakeLocalRank(),
        FakeDisplay(),
    ).player(
        RankPlayerCommand(rank_key="群星牌", player_id=26),
    )

    assert "50000 ~ 2000000000" in message


def test_rank_display_limit_is_validated_and_saved_by_service() -> None:
    display = FakeDisplay()

    message = _query_service(FakeLocalRank(), display).set_display_limit(
        group_id=123,
        user_id=456,
        can_manage=True,
        limit=30,
    )

    assert display.saved == (123, 456, 30)
    assert message.startswith("✅ 本群榜单默认显示条数已设置为 30 名")


@pytest.mark.asyncio
async def test_empty_local_rank_refresh_returns_without_headless() -> None:
    local_rank = FakeLocalRank()
    service = RankAdminService(
        RankAdminPolicy(
            rank_limit=100,
            batch_limit=100,
            refresh_limit=20,
            refresh_max_age_hours=24,
            page_cache_ttl_seconds=3600,
            display_limit=lambda _group_id: 20,
        ),
        cast("RankService", FakeRank()),
        cast("LocalRankService", local_rank),
        cast("RankPageRefreshService", SimpleNamespace()),
        cast("HeadlessService", NoHeadlessAccess()),
    )

    async def unused(_message: str = "") -> None:
        pytest.fail("empty cache must not report progress or release")

    message = await service.cache_refresh(
        progress=unused,
        release=unused,
    )

    assert message == "❌ 当前没有本地样本缓存。先查询一些米米号后再刷新。"
