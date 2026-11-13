from __future__ import annotations

import struct
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.config.models.seer import RankQueryConfig, SeerConfig
from ironsbot.core import time as clock
from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.headless_seer.rank import fetch_rank_page
from ironsbot.integrations.storage.rank_page_cache import SqliteRankPageCache
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.observation_cache import ObservationCache
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.player_query import (
    PLAYER_SOMUA_KEY,
    plan_player_detail_prompt,
    plan_player_query_sections,
    resolve_player_detail_reply,
)
from ironsbot.services.seer.player_service_support import background_refresh_kinds
from ironsbot.services.seer.player_shortcut_contracts import (
    PlayerShortcutCommand,
    PlayerShortcutDependencies,
    parse_player_shortcut_command,
)
from ironsbot.services.seer.player_shortcut_queries import fetch_player_shortcut_reply
from ironsbot.services.seer.rank import RankService
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_list_command,
    parse_rank_player_target_command,
    parse_rank_score_command,
)
from ironsbot.services.seer.rank_models import RankLookupCost, RankLookupResult
from ironsbot.services.seer.somua import (
    SOMUA_RANK_KEY,
    SOMUA_RANK_LIMIT,
    SOMUA_RANK_PAGE_SIZE,
    SOMUA_RANK_SUB_KEY,
    SOMUA_SCORE_PARAM,
    parse_somua_rank_page,
)

PLAYER = 700001
POINTS = 90
POSITION = 7
TWO_REQUESTS = 2
RANGE_FIRST = 21
RANGE_COUNT = 20

if TYPE_CHECKING:
    from pathlib import Path


def _wire(rows: list[tuple[int, int]]) -> bytes:
    return struct.pack("!I", len(rows)) + b"".join(
        struct.pack("!II16s", player, score, "示例".encode()) for player, score in rows
    )


def _rank(score: int = POINTS) -> RankLookupResult:
    return RankLookupResult(
        title="苏摩全服榜",
        score_name="分",
        rank=POSITION,
        score=score,
        queried=True,
        fetched_at=clock.now().timestamp(),
        cost=RankLookupCost(online_page_fetches=1),
    )


def _dependencies(result: RankLookupResult | Exception) -> PlayerShortcutDependencies:
    operation = AsyncMock(
        side_effect=result if isinstance(result, Exception) else None,
        return_value=result,
    )
    return PlayerShortcutDependencies(
        rank=cast("Any", SimpleNamespace(fetch_somua_summary=operation)),
        local_rank=cast("Any", None),
        timeout_seconds=1,
        detail_timeout_seconds=3,
        rank_timeout_seconds=1,
        observations=ObservationCache(),
        observation_ttl=300,
    )


def _game(score: int | Exception = POINTS) -> Any:
    return SimpleNamespace(
        send_and_wait=AsyncMock(
            side_effect=score if isinstance(score, Exception) else None,
            return_value=(None, SimpleNamespace(value=score)),
        ),
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="示例玩家")),
    )


async def _reply(dependencies: PlayerShortcutDependencies, game: Any, **kwargs: Any):
    return await fetch_player_shortcut_reply(
        dependencies,
        game,
        command=PlayerShortcutCommand("somua", PLAYER),
        player_id=PLAYER,
        **kwargs,
    )


def test_somua_menu_order_section_and_no_default_preheat() -> None:
    plan = plan_player_detail_prompt(
        has_collection=True,
        has_peak=True,
        has_autocard=True,
        has_somua=True,
        supports_conversation=True,
    )
    assert plan.prompt_lines[3:5] == ("3. 【群星牌】", "4. 【苏摩】")
    selected = resolve_player_detail_reply("4", selections=plan.builtin_selections)
    assert selected is not None and selected.key == PLAYER_SOMUA_KEY
    assert "somua" in SeerConfig().player.sections
    sections = plan_player_query_sections(
        ("autocard", "somua"), local_rank_enabled=False
    )
    assert sections.has_somua
    assert background_refresh_kinds(sections) == ("autocard",)
    assert not plan_player_query_sections(
        ("autocard",), local_rank_enabled=False
    ).has_somua


@pytest.mark.parametrize(
    "text,reference",
    [("苏摩", None), ("苏摩700001", "700001"), ("苏摩 玩家甲", "玩家甲")],
)
def test_somua_shared_shortcut_parser(text: str, reference: str | None) -> None:
    command = parse_player_shortcut_command(text)
    assert command is not None and command.kind == "somua"
    assert command.player_reference == reference


@pytest.mark.parametrize(
    "text",
    [
        "苏摩榜",
        "苏摩榜21-40",
        "苏摩榜第2页",
        "苏摩榜90分",
        "苏摩榜700001",
        "苏摩榜玩家甲",
    ],
)
def test_somua_board_is_not_claimed_as_a_player_alias(text: str) -> None:
    assert parse_player_shortcut_command(text) is None
    assert any(
        parser(text) is not None
        for parser in (
            parse_rank_list_command,
            parse_rank_player_target_command,
            parse_rank_score_command,
        )
    )


def test_somua_board_reuses_standard_list_range_score_and_target_grammar() -> None:
    listed = parse_rank_list_command("苏摩榜21-40")
    assert listed is not None and listed.rank_key == "苏摩"
    assert listed.start_rank == RANGE_FIRST and listed.limit == RANGE_COUNT
    scored = parse_rank_score_command("苏摩榜90分")
    assert scored is not None and scored.rank_key == "苏摩" and scored.score == POINTS
    player = parse_rank_player_target_command("苏摩榜玩家甲")
    assert player is not None and player.player_reference == "玩家甲"


@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
def test_somua_board_ownership_wins_over_a_visible_player_named_board(
    platform: Platform,
) -> None:
    resolver = PlayerIdResolver(
        lambda name, _conversation: PLAYER if name in {"榜", str(PLAYER)} else None,
        lambda _actor: PLAYER,
    )
    commands = {
        c.id: c
        for c in (
            *seer_command_contracts(resolver),
            *rank_help_command_contracts(resolver),
        )
    }
    shortcut = commands["seer.player.default"].routing_matcher
    board = commands["rank.global_collection"].routing_matcher
    assert shortcut is not None and board is not None
    actor = ActorRef(platform, "test-actor")
    conversation = ConversationRef(platform, "group", "test-group")
    for text, expected in (
        ("苏摩", True),
        (f"苏摩{PLAYER}", True),
        ("苏摩榜", False),
        ("苏摩榜21-40", False),
    ):
        context = MessageInputContext(
            IncomingMessageRef(platform, actor, conversation, "test-message", text),
            mentions_bot=True,
        )
        unified = command_context_from_input(context)
        assert shortcut(text, unified) is expected
        assert board(text, unified) is not expected


def test_somua_wire_uses_unsigned_score_and_fixed_utf8_name() -> None:
    parsed = parse_somua_rank_page(_wire([(PLAYER, POINTS), (PLAYER + 1, 0)]), 2)
    assert [(r.id, r.score, r.nick) for r in parsed] == [
        (PLAYER, POINTS, "示例"),
        (PLAYER + 1, 0, "示例"),
    ]


@pytest.mark.parametrize(
    "payload,limit",
    [
        (b"", 1),
        (struct.pack("!I", 1), 1),
        (_wire([(PLAYER, POINTS)]) + b"extra", 1),
        (_wire([(PLAYER, POINTS)]), 0),
        (_wire([(PLAYER, POINTS), (PLAYER, POINTS)]), 2),
        (_wire([(PLAYER, 0), (PLAYER + 1, POINTS)]), 2),
        (_wire([(0, POINTS)]), 1),
    ],
)
def test_somua_rejects_malformed_or_inconsistent_pages(
    payload: bytes, limit: int
) -> None:
    with pytest.raises(ValueError):
        parse_somua_rank_page(payload, limit)


@pytest.mark.asyncio
async def test_somua_transport_is_dedicated_and_capped() -> None:
    async def send(command: int, flag: int, start: int, end: int, **_: Any):
        assert command == SOMUA_RANK_KEY and flag == 1
        assert 0 <= start <= end < SOMUA_RANK_LIMIT
        assert end - start < SOMUA_RANK_PAGE_SIZE
        return None, _wire([(PLAYER + i, 2000 - i) for i in range(start, end + 1)])

    game = SimpleNamespace(send_and_wait=AsyncMock(side_effect=send))
    rows = await fetch_rank_page(
        cast("Any", game),
        key=SOMUA_RANK_KEY,
        sub_key=SOMUA_RANK_SUB_KEY,
        start=800,
        end=1200,
    )
    assert len(rows) == TWO_REQUESTS * SOMUA_RANK_PAGE_SIZE
    assert game.send_and_wait.await_count == TWO_REQUESTS
    assert (
        await fetch_rank_page(
            cast("Any", game),
            key=SOMUA_RANK_KEY,
            sub_key=SOMUA_RANK_SUB_KEY,
            start=1000,
            end=1100,
        )
        == []
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [POINTS, 0])
async def test_somua_score_and_rank_are_separate_successful_work(score: int) -> None:
    dependencies = _dependencies(_rank(score))
    game = _game(score)
    reply = await _reply(dependencies, game)
    assert reply.complete and f"积分：{score}" in reply.text
    assert f"第{POSITION}名" in reply.text
    assert reply.rank_lookup_should_charge_quota
    game.send_and_wait.assert_awaited_once_with(40002, PLAYER, SOMUA_SCORE_PARAM)


@pytest.mark.asyncio
async def test_somua_rank_timeout_keeps_score_and_only_bills_success() -> None:
    reply = await _reply(_dependencies(TimeoutError()), _game())
    assert f"积分：{POINTS}" in reply.text and "暂无法确认" in reply.text
    assert not reply.complete and reply.rank_lookup_should_charge_quota
    assert reply.query_work is not None
    assert reply.query_work.billable_units == frozenset(("somua_score",))


@pytest.mark.asyncio
async def test_somua_failed_rank_without_timestamp_preserves_score_observation() -> (
    None
):
    result = RankLookupResult(title="苏摩全服榜", score_name="分", failure="查询超时")
    reply = await _reply(_dependencies(result), _game())
    assert reply.fetched_at is not None
    assert "获取时间：未知" not in reply.text
    assert f"积分：{POINTS}" in reply.text and not reply.complete


@pytest.mark.asyncio
async def test_somua_score_failure_keeps_rank_and_board_score_without_zero() -> None:
    reply = await _reply(_dependencies(_rank()), _game(TimeoutError()))
    assert f"第{POSITION}名" in reply.text
    assert f"积分：{POINTS}（榜单记录）" in reply.text
    assert not reply.complete and "积分：0" not in reply.text


@pytest.mark.asyncio
async def test_somua_total_failure_is_not_billable() -> None:
    reply = await _reply(_dependencies(TimeoutError()), _game(TimeoutError()))
    assert not reply.complete and not reply.rank_lookup_should_charge_quota
    assert "暂无法获取" in reply.text and "第7名" not in reply.text


@pytest.mark.asyncio
async def test_somua_score_conflict_does_not_publish_confirmed_rank() -> None:
    result = _rank()
    result.observed_score = POINTS + 1
    reply = await _reply(_dependencies(result), _game())
    assert not reply.complete and f"积分：{POINTS}" in reply.text
    assert "数据不一致" in reply.text and "第7名" not in reply.text


@pytest.mark.asyncio
async def test_somua_restricted_search_is_not_reported_as_unranked() -> None:
    result = _rank()
    result.rank = None
    result.cost.restricted_miss = True
    reply = await _reply(_dependencies(result), _game())
    assert "暂无法确认" in reply.text and "未进入" not in reply.text
    assert not reply.complete


@pytest.mark.asyncio
async def test_somua_score_cache_ages_from_observation_not_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = [datetime.now(timezone.utc)]
    monkeypatch.setattr(clock, "now", lambda: current[0])
    dependencies = _dependencies(_rank())
    game = _game()
    await _reply(dependencies, game)
    current[0] += timedelta(seconds=290)
    second = await _reply(dependencies, game)
    assert game.send_and_wait.await_count == 1
    assert (
        second.query_work is not None
        and "somua_score" in second.query_work.cached_units
    )
    current[0] += timedelta(seconds=11)
    await _reply(dependencies, game)
    assert game.send_and_wait.await_count == TWO_REQUESTS


@pytest.mark.asyncio
async def test_somua_quota_exhaustion_does_not_fetch_fresh_score() -> None:
    result = _rank()
    result.cost = RankLookupCost(reused_successful_observation=True)
    dependencies = _dependencies(result)
    game = _game()
    reply = await _reply(dependencies, game, anchor_only=True)
    game.send_and_wait.assert_not_awaited()
    assert not reply.rank_lookup_should_charge_quota


@pytest.mark.asyncio
async def test_somua_rank_reuses_confirmed_position_and_invalidates_changed_score(
    tmp_path: Path,
) -> None:
    rows = parse_somua_rank_page(_wire([(PLAYER, POINTS)]), 1)
    fetch = AsyncMock(return_value=rows)
    service = RankService(
        RankQueryConfig(limit=1000),
        SqliteRankPageCache(
            tmp_path / "ranks.sqlite", enabled=True, ttl_seconds=300, allow_stale=True
        ),
        lambda: None,
        fetch,
    )
    first = await service.fetch_somua_summary(
        cast("Any", object()), PLAYER, score=POINTS
    )
    assert first.rank == 1
    count = fetch.await_count
    second = await service.fetch_somua_summary(
        cast("Any", object()), PLAYER, score=POINTS
    )
    assert second.cost.reused_successful_observation and fetch.await_count == count
    rows[0] = deepcopy(rows[0])
    changed = await service.fetch_somua_summary(
        cast("Any", object()), PLAYER, score=POINTS + 1
    )
    assert fetch.await_count > count
    assert not changed.cost.reused_successful_observation


@pytest.mark.asyncio
async def test_somua_same_score_requires_actual_player_identity_and_caps_limits(
    tmp_path: Path,
) -> None:
    rows = parse_somua_rank_page(_wire([(PLAYER + 1, POINTS), (PLAYER, POINTS)]), 2)
    service = RankService(
        RankQueryConfig(limit=50000, online_limit=50000),
        SqliteRankPageCache(
            tmp_path / "ties.sqlite", enabled=True, ttl_seconds=300, allow_stale=True
        ),
        lambda: None,
        AsyncMock(return_value=rows),
    )
    assert service._score_search_limit("苏摩") == SOMUA_RANK_LIMIT
    assert service._online_search_limit("苏摩") == SOMUA_RANK_LIMIT
    result = await service.fetch_somua_summary(
        cast("Any", object()), PLAYER, score=POINTS
    )
    assert result.rank == len(rows)
