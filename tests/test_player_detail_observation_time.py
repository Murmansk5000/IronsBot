# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.config.models.seer import SeerConfig
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.extensions.contracts import PlayerLineupCachedReply
from ironsbot.extensions.player_lineup import (
    PlayerLineupCacheServices,
    PlayerLineupQueryServices,
)
from ironsbot.services.seer.player_detail_service import PlayerDetailService
from ironsbot.services.seer.player_formatting_common import format_player_data_time
from ironsbot.services.seer.player_service_models import PlayerBaseSnapshot
from ironsbot.services.seer.player_shortcut_contracts import PlayerShortcutCommand
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakFetchResult,
    UnityPeakInfo,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.seer.player_shortcut_contracts import PlayerShortcutKind

PLAYER_ID = 123456
LIVE_AT = 1_800_000_000.0
BASE_AT = LIVE_AT - 60
RANK_AT = LIVE_AT - 120


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["collection", "peak", "autocard"])
@pytest.mark.parametrize(
    "evidence",
    [
        "old_rank",
        "old_snapshot",
        "unknown_rank",
        "unknown_snapshot",
        "timeout_fallback",
    ],
)
async def test_detail_observation_survives_composition_and_reply_reuse(
    monkeypatch: pytest.MonkeyPatch,
    kind: PlayerShortcutKind,
    evidence: str,
) -> None:
    clock = [LIVE_AT]
    monkeypatch.setattr(
        "ironsbot.core.time.now",
        lambda: datetime.fromtimestamp(clock[0], tz=timezone.utc),
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_detail_service.now",
        lambda: datetime.fromtimestamp(clock[0], tz=timezone.utc),
    )
    config = SeerConfig()
    result = RankLookupResult(
        title="rank",
        score_name="score",
        rank=4,
        score=1421,
        queried=True,
        fetched_at=None if evidence == "unknown_rank" else RANK_AT,
    )
    if evidence == "timeout_fallback":
        result.failure = "查询超时"
        result.fallback_cached_at = RANK_AT
    collection = PlayerRankSummary.empty()
    collection.book = result
    peak = PeakSeasonRankSummary.empty()
    peak.expert = result
    rank = SimpleNamespace(
        config=config.rank,
        current_peak_sub_key=lambda: 7,
        fetch_player_summary=AsyncMock(return_value=collection),
        fetch_peak_summary=AsyncMock(return_value=peak),
        fetch_autocard_summary=AsyncMock(return_value=result),
    )
    base_snapshot = None
    if evidence in {"old_snapshot", "unknown_snapshot"}:
        result.fetched_at = LIVE_AT
        base_snapshot = PlayerBaseSnapshot(
            player_id=PLAYER_ID,
            user_info=SimpleNamespace(nick="tester"),
            more_info=SimpleNamespace(total_achieve=100, pet_all_num=200),
            online_info=None,
            team_name="",
            fetched_at=None if evidence == "unknown_snapshot" else BASE_AT,
        )
    game = SimpleNamespace(
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="tester")),
        get_more_user_info=AsyncMock(
            return_value=SimpleNamespace(total_achieve=100, pet_all_num=200)
        ),
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_part_one",
        AsyncMock(return_value=UnityPartOneInfo(pet_kind_num=100, skin_num=20)),
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_peak_partial",
        AsyncMock(
            return_value=UnityPeakFetchResult(
                UnityPeakInfo(current_z_score=1421, current_z_all=10),
                frozenset(("standard", "wild", "expert")),
                fetched_at=LIVE_AT,
            )
        ),
    )
    service = PlayerDetailService(
        config,
        cast("Any", rank),
        cast("Any", SimpleNamespace(config=SimpleNamespace(enabled=False))),
        lambda coroutine, *, name: asyncio.create_task(coroutine, name=name),
    )
    command = PlayerShortcutCommand(
        kind=kind, player_id=PLAYER_ID, base_snapshot=base_snapshot
    )
    reply = await service.shortcut(cast("Any", game), command, PLAYER_ID)
    expected = {
        "old_rank": RANK_AT,
        "old_snapshot": BASE_AT,
        "unknown_rank": None,
        "unknown_snapshot": None,
        "timeout_fallback": RANK_AT,
    }
    assert reply.text.splitlines()[1] == format_player_data_time(expected[evidence])
    assert reply.fetched_at == expected[evidence]
    if evidence == "timeout_fallback":
        assert not reply.complete
        assert await service.cached_or_inflight_reply(PLAYER_ID, kind) is None
        return
    assert reply.complete
    if expected[evidence] is None:
        assert await service.cached_or_inflight_reply(PLAYER_ID, kind) is None
        return
    clock[0] += 30
    assert await service.shortcut(cast("Any", game), command, PLAYER_ID) is reply
    assert (
        sum(
            query.await_count
            for query in (
                rank.fetch_player_summary,
                rank.fetch_peak_summary,
                rank.fetch_autocard_summary,
            )
        )
        == 1
    )
    if base_snapshot is not None:
        game.get_user_info.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["collection", "peak"])
async def test_failed_rank_target_does_not_hide_other_data_time(
    monkeypatch: pytest.MonkeyPatch, kind: PlayerShortcutKind
) -> None:
    monkeypatch.setattr(
        "ironsbot.core.time.now",
        lambda: datetime.fromtimestamp(LIVE_AT, tz=timezone.utc),
    )
    config = SeerConfig()
    failed = RankLookupResult(
        title="rank", score_name="score", score=1421, failure="查询超时"
    )
    collection = PlayerRankSummary.empty()
    collection.achieve = failed
    peak = PeakSeasonRankSummary.empty()
    peak.standard = failed
    rank = SimpleNamespace(
        config=config.rank,
        current_peak_sub_key=lambda: 7,
        fetch_player_summary=AsyncMock(return_value=collection),
        fetch_peak_summary=AsyncMock(return_value=peak),
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_part_one",
        AsyncMock(return_value=UnityPartOneInfo()),
    )
    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcut_queries.fetch_unity_peak_partial",
        AsyncMock(
            return_value=UnityPeakFetchResult(
                UnityPeakInfo(),
                frozenset(("expert",)),
                fetched_at=LIVE_AT,
            )
        ),
    )
    service = PlayerDetailService(
        config,
        cast("Any", rank),
        cast("Any", SimpleNamespace(config=SimpleNamespace(enabled=False))),
        lambda coroutine, *, name: asyncio.create_task(coroutine, name=name),
    )
    game = SimpleNamespace(
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="tester")),
        get_more_user_info=AsyncMock(
            return_value=SimpleNamespace(
                total_achieve=100,
                pet_all_num=200,
            )
        ),
    )
    reply = await service.shortcut(
        cast("Any", game),
        PlayerShortcutCommand(kind=kind, player_id=PLAYER_ID),
        PLAYER_ID,
    )
    assert "查询超时" in reply.text
    assert not reply.complete
    assert reply.text.splitlines()[1] == format_player_data_time(LIVE_AT)


@pytest.mark.parametrize("timestamp", [None, 0.0, RANK_AT])
def test_formatter_never_reads_the_current_clock(
    monkeypatch: pytest.MonkeyPatch, timestamp: float | None
) -> None:
    def forbidden() -> None:
        pytest.fail("formatter must not fabricate an observation time")

    monkeypatch.setattr("ironsbot.core.time.now", forbidden)
    text = format_player_data_time(timestamp)
    if timestamp is None:
        assert text == "获取时间：未知"
    elif timestamp == 0:
        assert text == "获取时间：1970-01-01 08:00:00"
    else:
        assert text == "获取时间：2027-01-15 15:58:00"


@pytest.mark.asyncio
async def test_lineup_dates_data_before_bookkeeping_and_persistent_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = [LIVE_AT]
    monkeypatch.setattr(
        "ironsbot.core.time.now",
        lambda: datetime.fromtimestamp(clock[0], tz=timezone.utc),
    )
    game = SimpleNamespace(
        user_id=PLAYER_ID,
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="tester")),
        operations=SimpleNamespace(track=lambda *_args, **_kwargs: nullcontext()),
    )

    async def fetch_packet(
        client: Any, player_id: int, *, timeout_seconds: float
    ) -> bytes:
        assert client is not None and player_id == PLAYER_ID
        assert timeout_seconds == 1
        clock[0] += 10
        return b"packet"

    async def mark_available(**_kwargs: Any) -> None:
        clock[0] += 60

    query = PlayerLineupQueryServices(
        headless=cast(
            "Any", SimpleNamespace(get_game=lambda: game, mark_available=mark_available)
        ),
        error_message=cast("Any", object()),
    )
    result = await query.query(
        player_id=PLAYER_ID,
        actor=ActorRef(Platform.ONEBOT, "100"),
        conversation=ConversationRef(Platform.ONEBOT, "private", "100"),
        timeout_seconds=1,
        fetch_packet=fetch_packet,
    )
    assert not result.error
    assert result.payload == b"packet"
    assert result.leading_text.splitlines()[1] == format_player_data_time(LIVE_AT)
    path = str(tmp_path / "lineup.sqlite")
    cached = PlayerLineupCachedReply(
        leading_text=result.leading_text, text="", image=b"rendered"
    )
    PlayerLineupCacheServices().open(path).put(PLAYER_ID, cached)
    clock[0] += 3600
    assert PlayerLineupCacheServices().open(path).get(PLAYER_ID) == cached


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failures", "expected_error_fragment", "expected_calls"),
    [(1, "", 2), (2, "查询超时", 2)],
)
async def test_lineup_packet_retry_is_bounded_and_preserves_result(
    caplog: pytest.LogCaptureFixture,
    failures: int,
    expected_error_fragment: str,
    expected_calls: int,
) -> None:
    caplog.set_level("WARNING")
    game = SimpleNamespace(
        user_id=PLAYER_ID,
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="tester")),
        operations=SimpleNamespace(track=lambda *_args, **_kwargs: nullcontext()),
    )
    calls = 0

    async def fetch_packet(
        client: Any, player_id: int, *, timeout_seconds: float
    ) -> bytes:
        nonlocal calls
        assert client is not None and player_id == PLAYER_ID
        assert timeout_seconds == 1
        calls += 1
        if calls <= failures:
            raise TimeoutError
        return b"packet"

    query = PlayerLineupQueryServices(
        headless=cast(
            "Any",
            SimpleNamespace(
                get_game=lambda: game,
                mark_available=AsyncMock(),
            ),
        ),
        error_message=cast("Any", object()),
    )
    result = await query.query(
        player_id=PLAYER_ID,
        actor=ActorRef(Platform.ONEBOT, "100"),
        conversation=ConversationRef(Platform.ONEBOT, "private", "100"),
        timeout_seconds=1,
        fetch_packet=fetch_packet,
    )

    assert calls == expected_calls
    if expected_error_fragment:
        assert expected_error_fragment in result.error
    else:
        assert not result.error
        assert result.payload == b"packet"
    assert "attempt=1/2 error_type=TimeoutError" in caplog.text
