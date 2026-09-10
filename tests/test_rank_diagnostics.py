# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.core.rank_lookup_context import RankBudgetExhaustedError, rank_query_id
from ironsbot.integrations.storage.rank_page_cache import SqliteRankPageCache
from ironsbot.services.seer.rank import RankPageCache, RankService
from ironsbot.services.seer.rank_diagnostics import (
    RankEvidence,
    RankOrderError,
    diagnose_rank_query,
)
from ironsbot.services.seer.rank_formatting import format_rank_position_text
from ironsbot.services.seer.rank_models import RankEntry, RankLookupResult
from ironsbot.services.seer.rank_score_lookup import find_rank_by_score

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.operations.headless import HeadlessGame

GAME = cast("HeadlessGame", object())
PLAYER = 200_001
SCANNED_ROWS = 4
PAGE_SIZE = 3
MATCH_RANK = 2
PROFILE_SCORE = 4894
BOARD_SCORE = 4646


def build_service(
    tmp_path: Path, scores: list[int]
) -> tuple[RankService, SqliteRankPageCache]:
    entries = [
        RankEntry(PLAYER + index, "player", score) for index, score in enumerate(scores)
    ]
    cache = SqliteRankPageCache(
        tmp_path / "rank.sqlite",
        enabled=True,
        ttl_seconds=3600,
        allow_stale=True,
    )

    async def fetch(
        _game: Any, *, start: int, end: int, **_kwargs: Any
    ) -> list[RankEntry]:
        return entries[start : end + 1]

    service = RankService(
        RankQueryConfig(limit=20_000, online_limit=20_000, page_size=3),
        cast("RankPageCache", cache),
        lambda: None,
        fetch,
    )
    return service, cache


async def lookup(
    service: RankService, *, score: int | None = None, user_id: int = PLAYER
) -> RankLookupResult:
    return await service.find_rank(
        GAME,
        user_id=user_id,
        title="精灵图鉴",
        score_name="项",
        key=158,
        sub_key=1,
        target_score=score,
    )


@pytest.mark.asyncio
async def test_score_miss_is_not_twenty_thousand_player_absence(tmp_path: Path) -> None:
    service, cache = build_service(tmp_path, [4785, 4699, 4677, 4603])
    result = await lookup(service, score=4894, user_id=999_999)
    assert result.rank is None
    assert not result.scan_complete
    assert format_rank_position_text(result) == "名次未确认"
    assert cache.miss(key=158, sub_key=1, user_id=999_999, minimum_limit=1) is None


@pytest.mark.asyncio
async def test_linear_scan_certifies_actual_coverage_and_cached_miss(
    tmp_path: Path,
) -> None:
    service, cache = build_service(tmp_path, [4785, 4699, 4677, 4603])
    result = await lookup(service, user_id=999_999)
    assert result.scan_complete
    assert result.scanned_count == SCANNED_ROWS
    assert result.status == "scanned_missing"
    assert format_rank_position_text(result) == "已完整查询前4条，未找到该玩家"
    miss = cache.miss(key=158, sub_key=1, user_id=999_999, minimum_limit=1)
    assert miss is not None and miss.searched_limit == SCANNED_ROWS


@pytest.mark.asyncio
async def test_segmented_order_stops_lookup_without_caching_miss(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, cache = build_service(tmp_path, [4785, 4699, 443, 4907, 4906])
    with caplog.at_level(logging.INFO):
        result = await lookup(service, user_id=999_999)
    assert result.status == "order_anomaly"
    assert format_rank_position_text(result) == "榜单顺序异常，名次未确认"
    assert cache.miss(key=158, sub_key=1, user_id=999_999, minimum_limit=1) is None
    assert "inverted=True" in caplog.text
    assert "4907" in caplog.text and "443" in caplog.text
    start = next(
        record.getMessage()
        for record in caplog.records
        if "query start" in record.getMessage()
    )
    query_id = start.split("query=")[1].split()[0]
    assert f"query={query_id} status=order_anomaly" in caplog.text
    assert rank_query_id.get() == "-"


@pytest.mark.parametrize(
    "pages",
    [
        [(0, [(1, 443), (2, 4907)])],
        [(100, [(2, 4907)]), (0, [(1, 443)])],
        [(0, [(1, 4907)]), (100, [(1, 443)])],
        [(0, [(1, 4907)]), (0, [(2, 4907)])],
    ],
)
def test_page_order_duplicate_and_changed_position(
    pages: list[tuple[int, list[tuple[int, int]]]],
) -> None:
    evidence = RankEvidence()
    with pytest.raises(RankOrderError):
        for start, rows in pages:
            evidence.observe(
                key=158, sub_key=1, start=start, rows=rows, excluded=frozenset()
            )


def test_excluded_ids_do_not_trigger_order_check() -> None:
    evidence = RankEvidence()
    evidence.observe(
        key=158,
        sub_key=1,
        start=0,
        rows=[(1, -9557), (2, 4785), (1, -9557), (3, 4677)],
        excluded=frozenset({1}),
    )


@pytest.mark.asyncio
async def test_score_probe_budget_is_explicit() -> None:
    async def fetch_item(*_args: Any, index: int, **_kwargs: Any) -> RankEntry:
        return RankEntry(PLAYER + index, "player", 20_000 - index)

    async def fetch_page(*_args: Any, **_kwargs: Any) -> list[RankEntry]:
        return []

    result = await find_rank_by_score(
        GAME,
        user_id=PLAYER,
        key=158,
        sub_key=1,
        target_score=5000,
        limit=20_000,
        page_size=100,
        result=RankLookupResult(title="test", score_name="", queried=True),
        score_search_probe_limit=lambda _limit: 1,
        score_search_tie_page_limit=lambda: 1,
        fetch_rank_item=fetch_item,
        fetch_rank_page=fetch_page,
    )
    assert result.budget_exhausted
    assert format_rank_position_text(result) == "查询预算耗尽，名次未确认"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError(), RankBudgetExhaustedError()])
async def test_partial_scan_timeout_never_records_absence(
    tmp_path: Path,
    error: TimeoutError,
) -> None:
    service, cache = build_service(tmp_path, [9, 8, 7, 6])
    original = service.fetch_online_page

    async def fetch(*args: Any, **kwargs: Any) -> list[RankEntry]:
        if kwargs["start"]:
            raise error
        return await original(*args, **kwargs)

    service = RankService(service.config, service.cache, lambda: None, fetch)
    result = await lookup(service, user_id=999_999)
    assert not result.scan_complete
    assert result.scanned_count == PAGE_SIZE
    assert result.budget_exhausted == isinstance(error, RankBudgetExhaustedError)
    assert "未确认" in format_rank_position_text(result)
    assert cache.miss(key=158, sub_key=1, user_id=999_999, minimum_limit=1) is None


@pytest.mark.asyncio
async def test_cached_anchor_confirms_id_but_preserves_both_scores(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, cache = build_service(tmp_path, [4785, 4646, 4603])
    cache.save(
        key=158,
        sub_key=1,
        start=0,
        end=2,
        items=[
            RankEntry(PLAYER, "a", 4785),
            RankEntry(PLAYER + 1, "b", 4646),
            RankEntry(PLAYER + 2, "c", 4603),
        ],
    )
    with caplog.at_level(logging.INFO):
        result = await lookup(service, score=4894, user_id=PLAYER + 1)
    assert result.rank == MATCH_RANK
    assert result.profile_score == PROFILE_SCORE
    assert result.observed_score == BOARD_SCORE
    assert "rank score conflict" in caplog.text


@pytest.mark.asyncio
async def test_concurrent_queries_do_not_share_page_evidence(tmp_path: Path) -> None:
    first, _ = build_service(tmp_path / "a", [100, 90])
    second, _ = build_service(tmp_path / "b", [200, 190])
    results = await asyncio.gather(lookup(first), lookup(second))
    assert [result.rank for result in results] == [1, 1]


@pytest.mark.asyncio
async def test_cached_page_has_same_order_validation(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, cache = build_service(tmp_path, [])
    cache.save(
        key=158,
        sub_key=1,
        start=0,
        end=2,
        items=[
            RankEntry(PLAYER, "a", 4785),
            RankEntry(PLAYER + 1, "b", 443),
            RankEntry(PLAYER + 2, "c", 4907),
        ],
    )

    @diagnose_rank_query
    async def query() -> RankLookupResult:
        await service.fetch_page_result(
            GAME, key=158, sub_key=1, start=0, end=2, use_cache=True
        )
        return RankLookupResult(title="test", score_name="")

    with caplog.at_level(logging.INFO):
        result = await query()
    assert result.status == "order_anomaly"
    assert "source=cache" in caplog.text


@pytest.mark.asyncio
async def test_same_score_is_not_identity_confirmation(tmp_path: Path) -> None:
    service, cache = build_service(tmp_path, [4785, 4699, 4677])
    result = await lookup(service, score=4699, user_id=999_999)
    assert result.rank is None
    assert not result.scan_complete
    assert cache.miss(key=158, sub_key=1, user_id=999_999, minimum_limit=1) is None


@pytest.mark.asyncio
async def test_score_command_reports_anomaly_without_inventing_absence(
    tmp_path: Path,
) -> None:
    service, _ = build_service(tmp_path, [4785, 443, 4907])
    result = await service.fetch_score_segment(
        GAME,
        rank_key="精灵图鉴",
        key=158,
        sub_key=1,
        title="精灵图鉴榜",
        score_name="项",
        target_score=4907,
    )
    assert result.failure == "榜单顺序异常，名次未确认"
    assert not result.items


def test_migration_discards_legacy_misses_only(tmp_path: Path) -> None:
    path = tmp_path / "rank.sqlite"
    _, cache = build_service(tmp_path, [])
    cache.save(
        key=158, sub_key=1, start=0, end=0, items=[RankEntry(PLAYER, "player", 9)]
    )
    cache.save_miss(key=158, sub_key=1, user_id=999_999, searched_limit=20_000)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 3")
    _, updated = build_service(tmp_path, [])
    assert updated.miss(key=158, sub_key=1, user_id=999_999, minimum_limit=1) is None
    assert updated.item(key=158, sub_key=1, user_id=PLAYER) is not None
    updated.save_miss(key=158, sub_key=1, user_id=999_999, searched_limit=3)
    _, restarted = build_service(tmp_path, [])
    assert (
        restarted.miss(key=158, sub_key=1, user_id=999_999, minimum_limit=1) is not None
    )
