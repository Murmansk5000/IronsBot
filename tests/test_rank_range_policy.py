from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.integrations.headless_seer.rank import fetch_rank_page
from ironsbot.integrations.storage import rank_page_cache as storage
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.seer.rank import RankService
from ironsbot.services.seer.rank_admin import RankAdminPolicy, RankAdminService
from ironsbot.services.seer.rank_exclusions import RankExclusionPolicy
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    RankCacheBatchCommand,
    RankListCommand,
)
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_player_target_command,
)
from ironsbot.services.seer.rank_models import RankEntry
from ironsbot.services.seer.rank_queries import RankQueryPolicy, RankQueryService
from ironsbot.services.seer.rank_ranges import (
    MAX_RANK_INDEX,
    MAX_RANK_POSITION,
    RankRangeError,
    range_completion,
    validate_rank_interval,
)

if TYPE_CHECKING:
    from pathlib import Path

DEEP_START = 10001
LARGE_END = 999999999
DISPLAY_BUDGET = 100
RETAINED_PAGES = 3


@pytest.mark.parametrize("rank_key", list(GLOBAL_RANKS))
@pytest.mark.parametrize("position", [1000, 1001, 10001, 20001, MAX_RANK_POSITION])
@pytest.mark.asyncio
async def test_explicit_positions_ignore_search_budgets(
    tmp_path: Path, rank_key: str, position: int
) -> None:
    spec = GLOBAL_RANKS[rank_key]

    async def fetch(_game: Any, *, start: int, end: int, **_: Any) -> list[RankEntry]:
        return [
            RankEntry(
                index + 1, "玩家甲", index if spec.ascending else MAX_RANK_INDEX - index
            )
            for index in range(start, end + 1)
        ]

    transport = AsyncMock(side_effect=fetch)
    rank = RankService(
        RankQueryConfig(limit=1, online_limit=1),
        storage.SqliteRankPageCache(
            tmp_path / "rank.sqlite", enabled=True, ttl_seconds=300, allow_stale=True
        ),
        lambda: None,
        transport,
        exclusions=RankExclusionPolicy(frozenset(), {}),
    )
    result = await rank.fetch_visible_range_result(
        cast("Any", None),
        rank_key=rank_key,
        key=spec.key,
        sub_key=1,
        start_rank=position,
        count=1,
    )
    assert result.ranks == [position]
    assert len(result.items) == 1
    transport.assert_awaited_once()
    call = transport.await_args
    assert (
        call is not None and call.kwargs["start"] <= position - 1 <= call.kwargs["end"]
    )
    assert call.kwargs["end"] <= MAX_RANK_INDEX
    assert rank._online_search_limit(rank_key) == 1
    assert rank._score_search_limit(rank_key) == 1
    cached = rank.cached_visible_range_result(
        rank_key=rank_key, key=spec.key, sub_key=1, start_rank=position, count=1
    )
    assert cached is not None and cached.ranks == [position]
    assert cached.items == result.items
    raw_cached = await rank.fetch_range_result(
        cast("Any", None),
        key=spec.key,
        sub_key=1,
        start=position - 1,
        count=1,
        use_cache=True,
    )
    assert raw_cached.from_cache and raw_cached.items == result.items
    transport.assert_awaited_once()


@pytest.mark.parametrize(
    "text", ["苏摩榜10001名", "苏摩榜20001-999999999名", "苏摩榜第10001页"]
)
def test_parser_preserves_arbitrary_start_and_original_end(text: str) -> None:
    command = parse_rank_list_command(text)
    assert command is not None
    assert command.start_rank >= DEEP_START
    assert command.limit <= DISPLAY_BUDGET
    assert parse_rank_player_target_command(text) is None
    if "999999999" in text:
        assert command.end_rank == LARGE_END
        assert command.requested_end_rank == LARGE_END
    batch = parse_rank_cache_batch_command("/缓存榜单 苏摩榜 10001-999999999")
    assert (
        batch is not None
        and batch.start_rank == DEEP_START
        and batch.end_rank == LARGE_END
    )


@pytest.mark.parametrize("start,end", [(0, 1), (2, 1), (1, MAX_RANK_POSITION + 1)])
def test_illegal_intervals_are_not_normalized(start: int, end: int) -> None:
    with pytest.raises(RankRangeError):
        validate_rank_interval(start, end)


@pytest.mark.asyncio
@pytest.mark.parametrize("start,end", [(-1, 1), (2, 1), (0, MAX_RANK_INDEX + 1)])
async def test_transport_rejects_overflow_before_send(start: int, end: int) -> None:
    game = SimpleNamespace(send_and_wait=AsyncMock())
    with pytest.raises(RankRangeError):
        await fetch_rank_page(
            cast("Any", game), key=240, sub_key=1, start=start, end=end
        )
    game.send_and_wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_query_rejects_invalid_window_before_game_access() -> None:
    headless = SimpleNamespace(get_game=AsyncMock())
    service = RankQueryService(
        cast("Any", None),
        cast("Any", None),
        cast("Any", None),
        cast("Any", headless),
        RankQueryPolicy(
            player_error=lambda _id, error: str(error), player_timeout_seconds=1
        ),
    )
    command = parse_rank_list_command("苏摩榜20-1")
    assert command is not None
    reply = await service.prepare_list(command)
    assert not reply.request_succeeded and "范围无效" in reply.message
    headless.get_game.assert_not_called()


@pytest.mark.asyncio
async def test_local_samples_do_not_inherit_network_integer_boundary() -> None:
    headless = SimpleNamespace(get_game=AsyncMock())
    service = RankQueryService(
        cast("Any", None),
        cast("Any", SimpleNamespace(entries=lambda *_args, **_kwargs: ([], 0))),
        cast("Any", None),
        cast("Any", headless),
        RankQueryPolicy(
            player_error=lambda _id, error: str(error), player_timeout_seconds=1
        ),
    )
    reply = await service.prepare_list(
        RankListCommand("local", "精灵数量", MAX_RANK_POSITION + 1, 1)
    )
    assert "范围无效" not in reply.message
    headless.get_game.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("has_cache", [False, True])
async def test_offline_range_uses_cache_without_game_session(
    *, has_cache: bool
) -> None:
    from ironsbot.services.operations.headless_errors import NotLoggedInError

    cached = SimpleNamespace(
        items=[RankEntry(700001, "玩家甲", 10)], fetched_at=1_700_000_000, ranks=[1]
    )
    rank = SimpleNamespace(
        get_spec=lambda _key: GLOBAL_RANKS["苏摩"],
        spec_needs_sub_key=lambda _spec: False,
        cached_visible_range_result=lambda **_kwargs: cached if has_cache else None,
    )

    def offline() -> None:
        raise NotLoggedInError

    service = RankQueryService(
        cast("Any", rank),
        cast("Any", None),
        cast("Any", None),
        cast("Any", SimpleNamespace(get_game=offline)),
        RankQueryPolicy(
            player_error=lambda _id, error: str(error), player_timeout_seconds=1
        ),
    )
    reply = await service.prepare_list(RankListCommand("global", "苏摩", 1, 1))
    assert not reply.request_succeeded
    assert ("历史缓存" if has_cache else "没有可用的榜单缓存") in reply.message


@pytest.mark.asyncio
async def test_public_query_reports_original_and_budgeted_window() -> None:
    rows = [RankEntry(700001, "玩家甲", 10)]
    rank = SimpleNamespace(
        get_spec=lambda _key: GLOBAL_RANKS["苏摩"],
        spec_needs_sub_key=lambda _spec: False,
        fetch_visible_range_result=AsyncMock(
            return_value=SimpleNamespace(
                items=rows,
                ranks=[20001],
                fetched_at=1,
                incomplete_reason="服务端返回短页。",
            )
        ),
    )
    game = SimpleNamespace(
        operations=SimpleNamespace(track=lambda *_a, **_kw: nullcontext())
    )
    service = RankQueryService(
        cast("Any", rank),
        cast("Any", None),
        cast("Any", None),
        cast("Any", SimpleNamespace(get_game=lambda: game)),
        RankQueryPolicy(
            player_error=lambda _id, error: str(error), player_timeout_seconds=1
        ),
    )
    reply = await service.prepare_list(
        RankListCommand("global", "苏摩", 20001, 100, 30000)
    )
    assert "请求区间：第 20001-30000 名" in reply.message
    assert "执行区间：第 20001-20100 名" in reply.message
    assert "数量预算" in reply.message and "短页" in reply.message
    call = rank.fetch_visible_range_result.await_args
    assert call is not None and call.kwargs["count"] == DISPLAY_BUDGET


def test_partial_result_distinguishes_quantity_from_short_page() -> None:
    budget = range_completion(10001, 1000, 100, 100)
    assert "数量预算" in budget and "短页" not in budget
    short = range_completion(10001, 100, 100, 3)
    assert "短页" in short and "数量预算" not in short


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError(), ValueError("invalid wire count")])
async def test_public_query_reports_failure_without_claiming_empty_page(
    error: Exception,
) -> None:
    rank = SimpleNamespace(
        get_spec=lambda _key: GLOBAL_RANKS["苏摩"],
        spec_needs_sub_key=lambda _spec: False,
        fetch_visible_range_result=AsyncMock(side_effect=error),
        cached_visible_range_result=lambda **_kwargs: None,
    )
    game = SimpleNamespace(
        operations=SimpleNamespace(track=lambda *_a, **_kw: nullcontext())
    )
    service = RankQueryService(
        cast("Any", rank),
        cast("Any", None),
        cast("Any", None),
        cast("Any", SimpleNamespace(get_game=lambda: game)),
        RankQueryPolicy(
            player_error=lambda _id, failure: str(failure), player_timeout_seconds=1
        ),
    )
    reply = await service.prepare_list(RankListCommand("global", "苏摩", 20001, 1))
    assert not reply.request_succeeded
    assert "第 20001-20001 名" in reply.message and "未全部完成" in reply.message
    assert "空页" not in reply.message


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 2, DISPLAY_BUDGET])
async def test_batch_budget_keeps_high_start_and_reports_partial(count: int) -> None:
    from ironsbot.core.platform import ActorRef, Platform

    rank = SimpleNamespace(
        get_spec=lambda _key: GLOBAL_RANKS["苏摩"],
        spec_needs_sub_key=lambda _spec: False,
        fetch_visible_range_result=AsyncMock(
            return_value=SimpleNamespace(items=[object()] * count)
        ),
    )
    game = SimpleNamespace(
        operations=SimpleNamespace(track=lambda *_a, **_kw: nullcontext())
    )

    async def run(operation: Any, **_: Any) -> Any:
        return await operation()

    service = RankAdminService(
        RankAdminPolicy(1, DISPLAY_BUDGET, 1, 24, 300, lambda _conversation: 10),
        cast("Any", rank),
        cast("Any", None),
        cast("Any", None),
        cast("Any", SimpleNamespace(get_game=lambda: game)),
        cast("Any", SimpleNamespace(run=run)),
    )
    result = await service.prepare_cache_batch(
        RankCacheBatchCommand("苏摩", 10001, 20000),
        actor=ActorRef(Platform.ONEBOT, "synthetic-actor"),
        progress=AsyncMock(),
    )
    assert not result.request_succeeded
    assert "请求区间：第 10001-20000 名" in result.message
    assert "执行区间：第 10001-10100 名" in result.message
    assert "未全部完成" in result.message and "数量预算" in result.message
    call = rank.fetch_visible_range_result.await_args
    assert call is not None and call.kwargs["start_rank"] == DEEP_START
    assert call.kwargs["count"] == DISPLAY_BUDGET
    assert ("短页" in result.message) == (count < DISPLAY_BUDGET)


def test_targeted_somua_migration_preserves_valid_facts_and_other_boards(
    tmp_path: Path,
) -> None:
    path = tmp_path / "old.sqlite"
    old = SqliteDatabase(path, migrations=storage._MIGRATIONS[:4])
    with old.connect() as connection:
        for key, sub, start, end in [
            (45965, 1, 900, 999),
            (45965, 1, 900, 1099),
            (45965, 1, 1000, 1099),
            (240, 1, 1000, 1099),
            (45965, 2, 1000, 1099),
        ]:
            connection.execute(
                "INSERT INTO rank_pages VALUES (?, ?, ?, ?, 100, 1, 0, 0)",
                (key, sub, start, end),
            )
        connection.execute(
            "INSERT INTO player_rank_misses VALUES (45965, 1, 700001, 1000, 1)"
        )
        connection.execute(
            "INSERT INTO player_rank_misses VALUES (45965, 1, 700002, 2000, 1)"
        )
        connection.execute(
            "INSERT INTO player_rank_misses VALUES (240, 1, 700001, 1000, 1)"
        )
        connection.execute(
            "INSERT INTO player_rank_facts VALUES "
            "(45965, 1, 700001, 999, 1, '', 1, 900, 999)"
        )
        connection.execute(
            "INSERT INTO player_rank_last_seen VALUES (45965, 1, 700001, 999, 1, '', 1)"
        )
    for _ in range(2):
        database = SqliteDatabase(path, migrations=storage._MIGRATIONS)
        with database.connect() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM rank_pages").fetchone()[0]
                == RETAINED_PAGES
            )
            assert connection.execute(
                "SELECT key, searched_limit FROM player_rank_misses ORDER BY key"
            ).fetchall() == [(240, 1000), (45965, 1000)]
            assert connection.execute(
                "SELECT fetched_at FROM player_rank_facts"
            ).fetchall() == [(1.0,)]
            assert connection.execute(
                "SELECT fetched_at FROM player_rank_last_seen"
            ).fetchall() == [(1.0,)]
