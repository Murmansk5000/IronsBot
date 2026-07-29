from __future__ import annotations

import asyncio

import pytest

from ironsbot.config.models.seer import PlayerRankLookupConfig
from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.rank_player_scheduler import (
    PlayerRankLookupJob,
    current_player_rank_page_scheduler,
    run_player_rank_lookup_jobs,
)


def _job(
    job_id: str,
    events: list[str],
    *,
    pages: int = 2,
    timeout_once: bool = False,
) -> PlayerRankLookupJob:
    attempts = 0

    async def operation() -> RankLookupResult:
        nonlocal attempts
        scheduler = current_player_rank_page_scheduler()
        assert scheduler is not None
        for page in range(pages):
            async def fetch_page(page: int = page) -> None:
                nonlocal attempts
                attempts += 1
                events.append(f"{job_id}{page + 1}")
                if timeout_once and attempts == 1:
                    raise TimeoutError
                await asyncio.sleep(0)

            await scheduler.fetch_page(job_id, fetch_page)
        return RankLookupResult(title=job_id, score_name="分", rank=1)

    return PlayerRankLookupJob(
        id=job_id,
        title=job_id,
        key=1,
        sub_key=1,
        user_id=1,
        target_score=None,
        operation=operation,
    )


def test_player_rank_scheduler_rotates_after_each_page() -> None:
    events: list[str] = []
    results = asyncio.run(
        run_player_rank_lookup_jobs(
            [_job("a", events), _job("b", events), _job("c", events)],
            PlayerRankLookupConfig(),
        )
    )

    assert list(results) == ["a", "b", "c"]
    assert events == ["a1", "b1", "c1", "a2", "b2", "c2"]


def test_player_rank_scheduler_allows_configured_pages_per_turn() -> None:
    events: list[str] = []
    results = asyncio.run(
        run_player_rank_lookup_jobs(
            [_job("a", events), _job("b", events), _job("c", events)],
            PlayerRankLookupConfig(pages_per_turn=2),
        )
    )

    assert list(results) == ["a", "b", "c"]
    assert events == ["a1", "a2", "b1", "b2", "c1", "c2"]


def test_player_rank_scheduler_retries_timed_out_page_at_queue_tail() -> None:
    events: list[str] = []
    results = asyncio.run(
        run_player_rank_lookup_jobs(
            [_job("a", events, pages=1, timeout_once=True), _job("b", events, pages=1)],
            PlayerRankLookupConfig(page_retry_count=1),
        )
    )

    assert set(results) == {"a", "b"}
    assert events == ["a1", "b1", "a1"]


def test_player_rank_scheduler_timeout_yields_multiple_page_turn() -> None:
    events: list[str] = []
    results = asyncio.run(
        run_player_rank_lookup_jobs(
            [
                _job("a", events, pages=1, timeout_once=True),
                _job("b", events, pages=1),
            ],
            PlayerRankLookupConfig(page_retry_count=1, pages_per_turn=2),
        )
    )

    assert set(results) == {"a", "b"}
    assert events == ["a1", "b1", "a1"]


def test_player_rank_scheduler_marks_page_timeout_after_retry_limit() -> None:
    events: list[str] = []
    job = _job("a", events, pages=1, timeout_once=True)

    with pytest.raises(TimeoutError):
        asyncio.run(
            run_player_rank_lookup_jobs(
                [job],
                PlayerRankLookupConfig(page_retry_count=0),
            )
        )

    assert events == ["a1"]


def test_player_rank_scheduler_stops_new_pages_after_total_budget() -> None:
    events: list[str] = []

    async def slow_page() -> None:
        events.append("a1")
        await asyncio.sleep(0.08)

    async def first_operation() -> RankLookupResult:
        scheduler = current_player_rank_page_scheduler()
        assert scheduler is not None
        await scheduler.fetch_page("a", slow_page)
        return RankLookupResult(title="a", score_name="分")

    async def second_operation() -> RankLookupResult:
        scheduler = current_player_rank_page_scheduler()
        assert scheduler is not None
        await scheduler.fetch_page(
            "b",
            lambda: asyncio.sleep(0),
        )
        return RankLookupResult(title="b", score_name="分")

    first = PlayerRankLookupJob(
        id="a",
        title="a",
        key=1,
        sub_key=1,
        user_id=1,
        target_score=None,
        operation=first_operation,
    )
    second = PlayerRankLookupJob(
        id="b",
        title="b",
        key=2,
        sub_key=1,
        user_id=1,
        target_score=None,
        operation=second_operation,
    )

    with pytest.raises(TimeoutError):
        asyncio.run(
            run_player_rank_lookup_jobs(
                [first, second],
                PlayerRankLookupConfig(
                    page_timeout_seconds=0.05,
                    total_timeout_seconds=0.05,
                ),
            )
        )

    assert events == ["a1"]
