from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.services.seer.local_rank_models import LocalRankCacheStats
from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaDecision
from ironsbot.services.seer.rank_admin import (
    RankAdminPolicy,
    RankAdminService,
)
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    RankListCommand,
    RankPlayerCommand,
    RankScoreCommand,
)
from ironsbot.services.seer.rank_models import (
    RankEntry,
    RankLookupResult,
    RankPageResult,
    RankScoreSearchItem,
    RankScoreSearchResult,
)
from ironsbot.services.seer.rank_page_cache_models import CachedRankLookup
from ironsbot.services.seer.rank_queries import (
    RankQueryPolicy,
    RankQueryService,
)

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
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


class ExhaustedQuota:
    @staticmethod
    def check_general_query(**_kwargs: object) -> PlayerQueryQuotaDecision:
        return PlayerQueryQuotaDecision(allowed=False, message="额度已用完")

    @staticmethod
    def check(**_kwargs: object) -> PlayerQueryQuotaDecision:
        return PlayerQueryQuotaDecision(allowed=False, message="额度已用完")


class CachedGlobalRank:
    @staticmethod
    def get_spec(rank_key: str) -> object:
        return GLOBAL_RANKS[rank_key]

    @staticmethod
    def spec_needs_sub_key(_spec: object) -> bool:
        return False

    @staticmethod
    def cached_visible_range_result(**_kwargs: object) -> RankPageResult:
        return RankPageResult(
            items=[RankEntry(id=1, nick="cached", score=999)],
            fetched_at=1_781_234_567.0,
            from_cache=True,
        )

    @staticmethod
    def cached_score_segment(**_kwargs: object) -> RankScoreSearchResult:
        return RankScoreSearchResult(
            title="图鉴积分榜",
            score_name="分",
            target_score=999,
            searched_limit=10_000,
            queried=True,
            start_rank=1,
            end_rank=1,
            total_count=1,
            scanned_count=1,
            fetched_at=1_781_234_567.0,
            items=[
                RankScoreSearchItem(
                    id=1,
                    nick="cached",
                    score=999,
                    rank_index=0,
                )
            ],
        )

    @staticmethod
    def cached_player_lookup(
        **_kwargs: object,
    ) -> tuple[CachedRankLookup, RankLookupResult]:
        return (
            CachedRankLookup(
                id=123456789,
                nick="cached",
                score=999,
                rank_index=0,
                fetched_at=1_781_234_567.0,
            ),
            RankLookupResult(
                title="图鉴积分",
                score_name="分",
                rank=1,
                score=999,
                searched_limit=10_000,
                queried=True,
            ),
        )


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
    assert message.startswith("✅ 榜单默认显示条数已设置为 30 名")


@pytest.mark.asyncio
async def test_exhausted_quota_returns_cache_without_headless_access() -> None:
    service = RankQueryService(
        cast("RankService", CachedGlobalRank()),
        cast("LocalRankService", FakeLocalRank()),
        cast("RankDisplayService", FakeDisplay()),
        cast("HeadlessService", NoHeadlessAccess()),
        RankQueryPolicy(
            player_error=lambda _player_id, error: str(error),
            player_timeout_seconds=5,
        ),
        cast("Any", ExhaustedQuota()),
    )

    list_reply = await service.list_reply(
        RankListCommand(kind="global", rank_key="图鉴积分"),
        qq_user_id=1,
    )
    score_reply = await service.score_reply(
        RankScoreCommand(rank_key="图鉴积分", score=999),
        group_id=None,
        qq_user_id=1,
    )
    player_reply = await service.player_reply(
        RankPlayerCommand(rank_key="图鉴积分", player_id=123456789),
        qq_user_id=1,
    )

    assert "缓存数据" in list_reply.text
    assert "缓存数据" in score_reply.text
    assert "缓存数据" in player_reply.text
    assert "cached" in player_reply.text


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
        cast("PlayerRequestProtectionService", SimpleNamespace()),
    )

    async def unused(_message: str = "") -> None:
        pytest.fail("empty cache must not report progress or release")

    message = await service.cache_refresh(
        user_id=1,
        progress=unused,
    )

    assert message == "❌ 当前没有本地样本缓存。先查询一些米米号后再刷新。"
