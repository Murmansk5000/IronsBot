from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.services.seer.rank_list_global_messages import format_global_rank_message
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    RankListCommand,
    RankPlayerCommand,
    RankPlayerTargetCommand,
)
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_list_command,
    parse_rank_player_target_command,
    parse_rank_score_command,
)
from ironsbot.services.seer.rank_models import (
    RankEntry,
    RankLookupResult,
    RankPageResult,
)
from ironsbot.services.seer.rank_player_query import fetch_rank_player_result
from ironsbot.services.seer.rank_queries import RankQueryPolicy, RankQueryService
from ironsbot.services.seer.rank_range import fetch_rank_range_result
from ironsbot.services.seer.rank_score_lookup import find_rank_by_linear_scan

_FINISHED_AT = 1790233075


def test_beiming_commands_and_beijing_completion_time() -> None:
    spec = GLOBAL_RANKS["北冥试炼"]
    assert (spec.key, spec.sub_key, spec.ascending) == (
        267,
        1,
        True,
    )
    for alias in ("玄武榜", "北冥试炼榜"):
        assert parse_rank_list_command(alias) == RankListCommand(
            kind="global", rank_key="北冥试炼"
        )
        assert parse_rank_list_command(f"{alias}11-20") == RankListCommand(
            kind="global", rank_key="北冥试炼", start_rank=11, limit=10
        )
        assert parse_rank_player_target_command(
            f"{alias}700001"
        ) == RankPlayerTargetCommand("北冥试炼", "700001")
        assert parse_rank_player_target_command(f"{alias}玩家甲") == (
            RankPlayerTargetCommand("北冥试炼", "玩家甲")
        )
        assert parse_rank_score_command(f"{alias}5000分") is None
    message = format_global_rank_message(
        spec,
        [RankEntry(id=700001, nick="玩家甲", score=_FINISHED_AT)],
        timestamp="2026-09-25 12:00:00",
    )
    assert "1. 玩家甲（700001） 完成时间：2026-09-24 14:57:55" in message


@pytest.mark.asyncio
async def test_beiming_ascending_pages_and_player_scan() -> None:
    pages = {
        0: RankPageResult(
            [
                RankEntry(700001, "玩家甲", _FINISHED_AT),
                RankEntry(700002, "玩家乙", _FINISHED_AT + 1),
            ],
            fetched_at=1,
        ),
        2: RankPageResult(
            [RankEntry(700003, "玩家丙", _FINISHED_AT + 2)],
            fetched_at=2,
        ),
    }

    async def fetch_page(_game: object, **kwargs: Any) -> RankPageResult:
        return pages[kwargs["start"]]

    ranged = await fetch_rank_range_result(
        object(),
        key=267,
        sub_key=1,
        start=1,
        count=2,
        use_cache=False,
        rank_page_size=lambda: 2,
        fetch_rank_page_result=fetch_page,
        ascending=True,
    )
    assert [item.id for item in ranged.items] == [700002, 700003]
    found = await find_rank_by_linear_scan(
        object(),
        user_id=700003,
        key=267,
        sub_key=1,
        limit=3,
        page_size=2,
        result=RankLookupResult("玄武", "完成时间", searched_limit=3),
        fetch_rank_page=fetch_page,
        ascending=True,
    )
    assert (found.rank, found.score, found.failure) == (
        3,
        _FINISHED_AT + 2,
        None,
    )


@pytest.mark.asyncio
async def test_beiming_player_failure_is_not_reported_as_absence() -> None:
    rank = SimpleNamespace(
        get_spec=lambda _key: GLOBAL_RANKS["北冥试炼"],
        spec_needs_sub_key=lambda _spec: False,
        find_rank=AsyncMock(
            return_value=RankLookupResult(
                "北冥试炼·玄武",
                "",
                searched_limit=1200,
                queried=True,
                failure="连接已断开",
            )
        ),
    )
    game = SimpleNamespace(
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="玩家甲"))
    )
    result = await fetch_rank_player_result(
        cast("Any", rank),
        cast("Any", object()),
        game,
        command=RankPlayerCommand("北冥试炼", 700001),
    )
    assert "排名未确认：连接已断开" in result.message
    assert "未发现" not in result.message
    assert rank.find_rank.await_args.kwargs["search_limit"] is None
    rank.find_rank.return_value.failure = None
    result = await fetch_rank_player_result(
        cast("Any", rank),
        cast("Any", object()),
        game,
        command=RankPlayerCommand("北冥试炼", 700001),
    )
    assert "前 1200 名未发现" in result.message


@pytest.mark.asyncio
async def test_beiming_list_accepts_ranks_beyond_thousand() -> None:
    beyond_thousand = 1001
    page_size = 10
    fetch = AsyncMock(return_value=SimpleNamespace(items=[], fetched_at=0))
    rank = SimpleNamespace(
        get_spec=lambda _key: GLOBAL_RANKS["北冥试炼"],
        spec_needs_sub_key=lambda _spec: False,
        fetch_visible_range_result=fetch,
    )
    headless = SimpleNamespace(
        get_game=lambda: SimpleNamespace(
            operations=SimpleNamespace(track=lambda *_a, **_kw: nullcontext())
        )
    )
    service = RankQueryService(
        cast("Any", rank),
        cast("Any", object()),
        cast("Any", object()),
        cast("Any", headless),
        RankQueryPolicy(
            player_error=lambda _id, error: str(error), player_timeout_seconds=5
        ),
    )
    beyond = await service.prepare_list(
        RankListCommand("global", "北冥试炼", start_rank=beyond_thousand)
    )
    assert "仅记录前 1000 名" not in beyond.message
    assert fetch.await_args is not None
    assert fetch.await_args.kwargs["start_rank"] == beyond_thousand
    assert fetch.await_args.kwargs["count"] == page_size
    await service.prepare_list(
        RankListCommand("global", "北冥试炼", start_rank=995, limit=page_size)
    )
    assert fetch.await_args is not None
    assert fetch.await_args.kwargs["count"] == page_size
