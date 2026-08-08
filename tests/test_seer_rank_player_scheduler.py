from __future__ import annotations

import asyncio

from ironsbot.config.models.seer import PlayerRankLookupConfig
from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.rank_player_scheduler import (
    PlayerRankLookupJob,
    current_player_rank_page_scheduler,
    run_player_rank_lookup_jobs,
)


def _job(  # noqa: PLR0913 - mirrors the rank scheduler job contract
    job_id: str,
    events: list[str],
    *,
    pages: int = 2,
    release: asyncio.Event | None = None,
    started: dict[str, asyncio.Event] | None = None,
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
                label = f"{job_id}{page + 1}"
                events.append(label)
                if started is not None:
                    started.setdefault(label, asyncio.Event()).set()
                if timeout_once and attempts == 1:
                    raise TimeoutError
                if release is not None and page == 0:
                    await release.wait()
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


async def _wait_for_event_count(events: list[str], count: int) -> None:
    for _ in range(1000):
        if len(events) >= count:
            return
        await asyncio.sleep(0)
    assert len(events) >= count


def test_player_rank_scheduler_runs_independent_boards_concurrently() -> None:
    async def run() -> None:
        events: list[str] = []
        release = asyncio.Event()
        started: dict[str, asyncio.Event] = {}
        task = asyncio.create_task(
            run_player_rank_lookup_jobs(
                [
                    _job("a", events, pages=1, release=release, started=started),
                    _job("b", events, pages=1, release=release, started=started),
                    _job("c", events, pages=1, release=release, started=started),
                ],
                PlayerRankLookupConfig(),
            )
        )
        await _wait_for_event_count(events, 3)
        assert set(events) == {"a1", "b1", "c1"}
        release.set()
        results = await task
        assert set(results) == {"a", "b", "c"}

    asyncio.run(run())


def test_player_rank_scheduler_keeps_one_page_in_flight_per_board() -> None:
    async def run() -> None:
        events: list[str] = []
        release = asyncio.Event()
        started: dict[str, asyncio.Event] = {}
        task = asyncio.create_task(
            run_player_rank_lookup_jobs(
                [
                    _job("a", events, pages=2, release=release, started=started),
                    _job("b", events, pages=1, release=release, started=started),
                ],
                PlayerRankLookupConfig(),
            )
        )
        await _wait_for_event_count(events, 2)
        assert set(events) == {"a1", "b1"}
        assert "a2" not in events
        release.set()
        await task
        assert events.index("a2") > events.index("a1")

    asyncio.run(run())


def test_player_rank_scheduler_retries_timed_out_page() -> None:
    events: list[str] = []
    results = asyncio.run(
        run_player_rank_lookup_jobs(
            [_job("a", events, pages=1, timeout_once=True)],
            PlayerRankLookupConfig(page_retry_count=1),
        )
    )

    assert set(results) == {"a"}
    assert events == ["a1", "a1"]


def test_player_rank_scheduler_keeps_other_jobs_after_one_job_exceeds_budget() -> None:
    events: list[str] = []

    async def slow_page() -> None:
        events.append("a1")
        await asyncio.sleep(0.08)

    async def operation() -> RankLookupResult:
        scheduler = current_player_rank_page_scheduler()
        assert scheduler is not None
        await scheduler.fetch_page("a", slow_page)
        return RankLookupResult(title="a", score_name="分")

    slow_job = PlayerRankLookupJob(
        id="a",
        title="a",
        key=1,
        sub_key=1,
        user_id=1,
        target_score=None,
        operation=operation,
    )

    async def complete_operation() -> RankLookupResult:
        return RankLookupResult(title="b", score_name="分", rank=1)

    complete_job = PlayerRankLookupJob(
        id="b",
        title="b",
        key=1,
        sub_key=1,
        user_id=1,
        target_score=None,
        operation=complete_operation,
    )

    results = asyncio.run(
        run_player_rank_lookup_jobs(
            [slow_job, complete_job],
            PlayerRankLookupConfig(
                page_timeout_seconds=0.05,
                total_timeout_seconds=0.05,
                page_retry_count=0,
            ),
        )
    )

    assert events == ["a1"]
    assert results["a"].failure == "查询超时"
    assert results["b"].rank == 1
