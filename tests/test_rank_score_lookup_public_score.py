# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging

from ironsbot.services.seer.rank_live_lookup import _log_rank_score_mismatch
from ironsbot.services.seer.rank_models import RankEntry, RankLookupResult
from ironsbot.services.seer.rank_score_lookup import find_rank_by_score

PLAYER_ID = 500_797_823
PUBLIC_SCORE = 400_183
PUBLIC_SCORE_BEHIND = 400_086
EXPECTED_RANK = 2


def test_player_is_confirmed_near_ahead_of_rank_score() -> None:
    entries = (
        RankEntry(id=669_890_126, nick="first", score=400_220),
        RankEntry(id=PLAYER_ID, nick="second", score=400_182),
        RankEntry(id=1, nick="third", score=400_180),
    )
    page_requests: list[tuple[int, int]] = []

    async def fetch_item(
        _game: object,
        *,
        index: int,
        **_kwargs: object,
    ) -> RankEntry | None:
        return entries[index] if 0 <= index < len(entries) else None

    async def fetch_page(
        _game: object,
        *,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[RankEntry]:
        page_requests.append((start, end))
        return list(entries[start : end + 1])

    result = asyncio.run(
        find_rank_by_score(
            object(),
            user_id=PLAYER_ID,
            key=182,
            sub_key=20_260_717,
            target_score=PUBLIC_SCORE,
            limit=len(entries),
            page_size=100,
            result=RankLookupResult(title="狂野赛季榜", score_name="段位分"),
            score_search_probe_limit=lambda _limit: 16,
            score_search_tie_page_limit=lambda: 5,
            fetch_rank_item=fetch_item,
            fetch_rank_page=fetch_page,
            allow_nearby_player_lookup=True,
        )
    )

    assert result.rank == EXPECTED_RANK
    assert result.score == PUBLIC_SCORE
    assert page_requests == [(0, 2)]


def test_player_is_confirmed_near_behind_rank_score() -> None:
    entries = (
        RankEntry(id=669_890_126, nick="first", score=400_220),
        RankEntry(id=PLAYER_ID, nick="second", score=400_087),
        RankEntry(id=1, nick="third", score=400_086),
    )

    async def fetch_item(
        _game: object,
        *,
        index: int,
        **_kwargs: object,
    ) -> RankEntry | None:
        return entries[index] if 0 <= index < len(entries) else None

    async def fetch_page(
        _game: object,
        *,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[RankEntry]:
        return list(entries[start : end + 1])

    result = asyncio.run(
        find_rank_by_score(
            object(),
            user_id=PLAYER_ID,
            key=182,
            sub_key=20_260_717,
            target_score=PUBLIC_SCORE_BEHIND,
            limit=len(entries),
            page_size=100,
            result=RankLookupResult(title="狂野赛季榜", score_name="段位分"),
            score_search_probe_limit=lambda _limit: 16,
            score_search_tie_page_limit=lambda: 5,
            fetch_rank_item=fetch_item,
            fetch_rank_page=fetch_page,
            allow_nearby_player_lookup=True,
        )
    )

    assert result.rank == EXPECTED_RANK
    assert result.score == PUBLIC_SCORE_BEHIND


def test_logs_observed_rank_score_mismatch(
    caplog: object,
) -> None:
    result = RankLookupResult(
        title="成就点数榜",
        score_name="成就点数",
        rank=12,
        score=10_195,
        observed_score=10_194,
    )

    with caplog.at_level(  # type: ignore[union-attr]
        logging.WARNING,
        logger="ironsbot.services.seer.rank_live_lookup",
    ):
        _log_rank_score_mismatch(
            result,
            rank_key="成就点数",
            key=17,
            sub_key=0,
            user_id=123_456_789,
            expected_score=10_195,
            cached_score=10_194,
        )

    assert "player rank score mismatch" in caplog.text  # type: ignore[union-attr]
    assert "rank_key=成就点数" in caplog.text  # type: ignore[union-attr]
    assert "key=17" in caplog.text  # type: ignore[union-attr]
    assert "reference=public" in caplog.text  # type: ignore[union-attr]
    assert "reference_score=10195" in caplog.text  # type: ignore[union-attr]
    assert "observed_score=10194" in caplog.text  # type: ignore[union-attr]


def test_logs_cached_rank_score_mismatch_without_public_score(
    caplog: object,
) -> None:
    result = RankLookupResult(
        title="群星之巅榜",
        score_name="分",
        rank=12,
        score=6_088,
        observed_score=6_088,
    )

    with caplog.at_level(  # type: ignore[union-attr]
        logging.WARNING,
        logger="ironsbot.services.seer.rank_live_lookup",
    ):
        _log_rank_score_mismatch(
            result,
            rank_key="群星之巅",
            key=240,
            sub_key=1,
            user_id=123_456_789,
            expected_score=None,
            cached_score=6_087,
        )

    assert "reference=cached" in caplog.text  # type: ignore[union-attr]
    assert "reference_score=6087" in caplog.text  # type: ignore[union-attr]
    assert "observed_score=6088" in caplog.text  # type: ignore[union-attr]
