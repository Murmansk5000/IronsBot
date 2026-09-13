from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.local_rank_models import LocalRankCacheStats
from ironsbot.services.seer.rank_admin import (
    RankAdminPolicy,
    RankAdminService,
)
from ironsbot.services.seer.rank_list_models import (
    GlobalRankSpec,
    RankCacheBatchCommand,
    RankListCommand,
    RankPlayerCommand,
)
from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.rank_pagination import RankPageConflictError
from ironsbot.services.seer.rank_player_query import RankPlayerQueryResult
from ironsbot.services.seer.rank_queries import (
    RankQueryPolicy,
    RankQueryService,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

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
        self.saved: tuple[ConversationRef, ActorRef, int] | None = None

    @staticmethod
    def limit_for_conversation(_conversation: ConversationRef | None) -> int:
        return 20

    def set_conversation_limit(
        self,
        conversation: ConversationRef,
        actor: ActorRef,
        limit: int,
    ) -> None:
        self.saved = conversation, actor, limit


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
async def test_rank_page_conflict_is_reported_without_false_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _query_service(FakeLocalRank(), FakeDisplay())
    monkeypatch.setattr(
        service, "_run_headless_request", AsyncMock(side_effect=RankPageConflictError())
    )
    message = await service.list(RankListCommand(kind="global", rank_key="图鉴积分"))
    assert message == str(RankPageConflictError())


@pytest.mark.asyncio
async def test_local_season_failure_does_not_read_unscoped_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = DataUnavailableError("巅峰赛季数据读取失败")
    monkeypatch.setattr(FakeRank, "current_peak_sub_key", Mock(side_effect=error))
    local = FakeLocalRank()
    entries = Mock(side_effect=AssertionError("must not read all seasons"))
    monkeypatch.setattr(local, "entries", entries)
    message = await _query_service(local, FakeDisplay()).list(
        RankListCommand(kind="local", rank_key="专家段位")
    )
    assert message == str(error)
    entries.assert_not_called()


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


@pytest.mark.asyncio
async def test_prepared_rank_player_query_records_quota_after_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _query_service(FakeLocalRank(), FakeDisplay())
    lookup = RankLookupResult(
        title="成就点数",
        score_name="点",
        rank=1,
        queried=True,
    )
    lookup.cost.page_starts.append(1)
    monkeypatch.setattr(
        service,
        "_run_headless_request",
        AsyncMock(return_value=RankPlayerQueryResult("result", lookup)),
    )
    record = Mock()
    monkeypatch.setattr(service, "_record_successful_player_quota", record)
    command = RankPlayerCommand(rank_key="成就点数", player_id=123456)

    prepared = await service.prepare_player(command)

    assert prepared.message == "result"
    record.assert_not_called()
    prepared.delivered()
    record.assert_called_once_with(command, None)


def test_rank_display_limit_is_validated_and_saved_by_service() -> None:
    display = FakeDisplay()

    message = _query_service(FakeLocalRank(), display).set_display_limit(
        conversation=ConversationRef(Platform.ONEBOT, "group", "123"),
        actor=ActorRef(Platform.ONEBOT, "456"),
        can_manage=True,
        limit=30,
    )

    assert display.saved == (
        ConversationRef(Platform.ONEBOT, "group", "123"),
        ActorRef(Platform.ONEBOT, "456"),
        30,
    )
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
        cast("PlayerRequestProtectionService", SimpleNamespace()),
    )

    async def unused(_message: str = "") -> None:
        pytest.fail("empty cache must not report progress or release")

    message = await service.cache_refresh(
        actor=ActorRef(Platform.ONEBOT, "1"),
        progress=unused,
    )

    assert message == "❌ 当前没有本地样本缓存。先查询一些米米号后再刷新。"


@pytest.mark.asyncio
async def test_rank_batch_reports_progress_before_starting_headless_request() -> None:
    events: list[str] = []
    spec = GlobalRankSpec("图鉴积分榜", key=1, sub_key=2, unit="分")

    class Rank:
        @staticmethod
        def get_spec(_rank_key: str) -> GlobalRankSpec:
            return spec

        @staticmethod
        def spec_needs_sub_key(_spec: GlobalRankSpec) -> bool:
            return False

        @staticmethod
        async def fetch_range(*_args: object, **kwargs: object) -> list[object]:
            events.append(f"fetch:{kwargs['count']}")
            return [object()] * 20

    class Operations:
        @staticmethod
        @contextmanager
        def track(*_args: object, **_kwargs: object) -> Iterator[None]:
            yield

    class Headless:
        @staticmethod
        def get_game() -> object:
            events.append("get-game")
            return SimpleNamespace(operations=Operations())

    class Requests:
        @staticmethod
        async def run(operation: Any, **_kwargs: object) -> int:
            events.append("request")
            return await operation()

    service = RankAdminService(
        RankAdminPolicy(
            rank_limit=100,
            batch_limit=20,
            refresh_limit=20,
            refresh_max_age_hours=24,
            page_cache_ttl_seconds=3600,
            display_limit=lambda _conversation: 20,
        ),
        cast("RankService", Rank()),
        cast("LocalRankService", FakeLocalRank()),
        cast("RankPageRefreshService", SimpleNamespace()),
        cast("HeadlessService", Headless()),
        cast("PlayerRequestProtectionService", Requests()),
    )

    async def progress(message: str) -> None:
        assert "本次最多请求 20 条" in message
        events.append("progress")

    result = await service.cache_batch(
        RankCacheBatchCommand("图鉴积分", 1, 50),
        actor=ActorRef(Platform.ONEBOT, "1"),
        progress=progress,
    )

    assert events == ["progress", "request", "get-game", "fetch:20"]
    assert "写入榜单页缓存：20 条" in result
