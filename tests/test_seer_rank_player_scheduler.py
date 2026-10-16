from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from ironsbot.config.models.seer import PlayerRankLookupConfig
from ironsbot.core.rank_lookup_context import RankPagePolicy, rank_page_policy
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


def _phased_job(
    job_id: str,
    phases: tuple[str, ...],
    events: list[str],
    release: asyncio.Event | None = None,
) -> PlayerRankLookupJob:
    async def operation() -> RankLookupResult:
        scheduler = current_player_rank_page_scheduler()
        assert scheduler is not None
        for index, phase in enumerate(phases):

            async def fetch(index: int = index, phase: str = phase) -> None:
                events.append(f"{job_id}:{phase}:{index}")
                if index == 0 and release is not None:
                    await release.wait()
                await asyncio.sleep(0)

            token = rank_page_policy.set(RankPagePolicy(phase))
            try:
                await scheduler.fetch_page(job_id, fetch)
            finally:
                rank_page_policy.reset(token)
            await asyncio.sleep(0)
        return RankLookupResult(title=job_id, score_name="score", rank=1)

    return replace(_job(job_id, events), operation=operation)


def test_all_anchor_neighbors_finish_before_any_broad_search() -> None:
    async def run() -> None:
        events: list[str] = []
        release = asyncio.Event()
        task = asyncio.create_task(
            run_player_rank_lookup_jobs(
                [
                    _phased_job(
                        "cached",
                        ("recent_anchor", "cached_window", "cached_window", "search"),
                        events,
                        release,
                    ),
                    _phased_job("other", ("cached_window", "search"), events),
                    _phased_job("unknown", ("linear_scan",), events),
                ],
                PlayerRankLookupConfig(),
            )
        )
        await _wait_for_event_count(events, 2)
        assert set(events) == {"cached:recent_anchor:0", "other:cached_window:0"}
        release.set()
        results = await asyncio.wait_for(task, 1)
        last_anchor = events.index("cached:cached_window:2")
        assert events.index("other:search:1") > last_anchor
        assert events.index("cached:search:3") > last_anchor
        assert events.index("unknown:linear_scan:0") > last_anchor
        assert all(result.rank == 1 for result in results.values())

    asyncio.run(run())


@pytest.mark.parametrize("fails", [False, True])
def test_anchor_job_without_pages_does_not_block_other_searches(*, fails: bool) -> None:
    async def run() -> None:
        events: list[str] = []

        async def finish() -> RankLookupResult:
            if fails:
                raise ConnectionError("unavailable")
            return RankLookupResult(title="cached", score_name="score", rank=1)

        results = await asyncio.wait_for(
            run_player_rank_lookup_jobs(
                [
                    replace(_job("cached", events), operation=finish, priority_group=0),
                    _phased_job("unknown", ("linear_scan",), events),
                ],
                PlayerRankLookupConfig(),
            ),
            1,
        )
        assert events == ["unknown:linear_scan:0"]
        assert results["unknown"].rank == 1
        assert results["cached"].failure == ("查询失败" if fails else None)

    asyncio.run(run())


def test_page_priority_prefers_known_score_to_linear_scan() -> None:
    async def run() -> None:
        events: list[str] = []
        jobs = [
            _phased_job("unknown", ("linear_scan",), events),
            *(
                _phased_job(f"known{index}", ("score_probe",), events)
                for index in range(3)
            ),
        ]
        await run_player_rank_lookup_jobs(jobs, PlayerRankLookupConfig())
        assert events[-1] == "unknown:linear_scan:0"

    asyncio.run(run())


def test_anchor_timeout_releases_waiting_searches_within_total_budget() -> None:
    async def run() -> None:
        events: list[str] = []
        results = await asyncio.wait_for(
            run_player_rank_lookup_jobs(
                [
                    _phased_job("cached", ("cached_window",), events, asyncio.Event()),
                    _phased_job("unknown", ("linear_scan",), events),
                ],
                PlayerRankLookupConfig(
                    page_timeout_seconds=0.02,
                    total_timeout_seconds=0.02,
                    page_retry_count=0,
                ),
            ),
            1,
        )
        assert events == ["cached:cached_window:0"]
        assert all(result.failure == "查询超时" for result in results.values())

    asyncio.run(run())


def test_rank_confirmation_precedes_exclusion_prefix_and_unknown_scan() -> None:
    async def run() -> None:
        events: list[str] = []
        await run_player_rank_lookup_jobs(
            [
                _phased_job("unknown", ("linear_scan",), events),
                *(
                    _phased_job(f"prefix{index}", ("exclusion_prefix",), events)
                    for index in range(3)
                ),
                *(
                    _phased_job(f"known{index}", ("score_probe",), events)
                    for index in range(3)
                ),
            ],
            PlayerRankLookupConfig(),
        )
        assert all(":score_probe:" in event for event in events[:3])
        assert all(":exclusion_prefix:" in event for event in events[3:6])
        assert events[-1] == "unknown:linear_scan:0"

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


def test_self_cancelled_page_propagates_and_clears_scheduler_context() -> None:
    async def run() -> None:
        cleaned_contexts: list[bool] = []
        loader_finalized = asyncio.Event()

        async def loader() -> None:
            try:
                raise asyncio.CancelledError
            finally:
                loader_finalized.set()

        async def operation() -> RankLookupResult:
            scheduler = current_player_rank_page_scheduler()
            assert scheduler is not None
            await scheduler.fetch_page("self_cancelled", loader)
            return RankLookupResult(title="self_cancelled", score_name="score")

        job = replace(_job("self_cancelled", [], pages=0), operation=operation)

        async def lookup() -> None:
            try:
                await run_player_rank_lookup_jobs([job], PlayerRankLookupConfig())
            finally:
                cleaned_contexts.append(current_player_rank_page_scheduler() is None)

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(lookup(), timeout=1.0)
        assert loader_finalized.is_set()
        assert cleaned_contexts == [True]
        assert current_player_rank_page_scheduler() is None
        assert not (asyncio.all_tasks() - {asyncio.current_task()})

    asyncio.run(run())
