from __future__ import annotations

import asyncio
from collections import Counter
from itertools import cycle
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.config.models.seer import RankPageRefreshConfig
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.seer.rank_list_models import GlobalRankSpec
from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService
from ironsbot.services.seer.rank_page_refresh_models import RankPageRefreshTarget

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest import MonkeyPatch

    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.seer.rank import RankService


TARGET_COUNT = 8
BACKGROUND_TARGET_COUNT = 3
MANUAL_TARGET_COUNT = 2


def _targets(count: int) -> list[RankPageRefreshTarget]:
    spec = GlobalRankSpec("测试榜", key=1, sub_key=2, unit="分")
    return [
        RankPageRefreshTarget(
            rank_key="测试榜",
            spec=spec,
            reason="缺失",
            start_rank=index * 100 + 1,
            end_rank=index * 100 + 100,
            raw_start=index * 100,
            raw_end=index * 100 + 99,
        )
        for index in range(count)
    ]


class _Rank:
    def __init__(
        self,
        gates: dict[int, asyncio.Event] | None = None,
        *,
        failures: set[int] | None = None,
    ) -> None:
        self.events: list[tuple[int, int]] = []
        self.started: dict[int, asyncio.Event] = {}
        self._gates = gates or {}
        self._failures = failures or set()

    async def fetch_range(
        self,
        game: HeadlessGame,
        *,
        start: int,
        **_kwargs: object,
    ) -> None:
        self.events.append((game.user_id, start))
        self.started.setdefault(start, asyncio.Event()).set()
        if gate := self._gates.get(start):
            await gate.wait()
        if start in self._failures:
            raise TimeoutError


def _games(count: int) -> Callable[[], HeadlessGame]:
    workers = cycle(
        [
            cast(
                "HeadlessGame",
                SimpleNamespace(
                    user_id=10000 + index,
                    operations=HeadlessOperationTracker(),
                ),
            )
            for index in range(count)
        ]
    )
    return lambda: next(workers)


async def _wait_for_event_count(
    events: list[tuple[int, int]],
    count: int,
) -> None:
    for _ in range(1000):
        if len(events) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError


def _service(
    targets: list[RankPageRefreshTarget],
    rank: _Rank,
    monkeypatch: MonkeyPatch,
    **config: object,
) -> RankPageRefreshService:
    config_values: dict[str, object] = {
        "pages_per_run": len(targets),
        "pages_per_run_min": 0,
    }
    config_values.update(config)
    service = RankPageRefreshService(
        RankPageRefreshConfig.model_validate(config_values),
        cast("RankService", rank),
    )
    monkeypatch.setattr(
        RankPageRefreshService,
        "preview",
        lambda _service, _rank_keys=None, *, limit=None: (
            targets if limit is None else targets[:limit]
        ),
    )
    return service


@pytest.mark.asyncio
async def test_refresh_chooses_total_page_budget_before_target_selection(
    monkeypatch: MonkeyPatch,
) -> None:
    targets = _targets(MANUAL_TARGET_COUNT)
    rank = _Rank()
    service = _service(
        targets,
        rank,
        monkeypatch,
        pages_per_run_min=1,
    )
    requested_limits: list[int | None] = []

    def preview(
        _service: RankPageRefreshService,
        _rank_keys: object = None,
        *,
        limit: int | None = None,
    ) -> list[RankPageRefreshTarget]:
        requested_limits.append(limit)
        return targets[:limit]

    monkeypatch.setattr(RankPageRefreshService, "preview", preview)
    monkeypatch.setattr(
        "ironsbot.services.seer.rank_page_refresh.random.randint",
        lambda _minimum, _maximum: 1,
    )

    result = await service.refresh(_games(1), background=True)

    assert requested_limits == [1]
    assert result.total == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_count", [1, 2, 3, 4])
async def test_background_refresh_uses_no_more_than_healthy_worker_count(
    monkeypatch: MonkeyPatch,
    worker_count: int,
) -> None:
    targets = _targets(TARGET_COUNT)
    gates = {target.raw_start: asyncio.Event() for target in targets}
    rank = _Rank(gates)
    service = _service(targets, rank, monkeypatch)

    task = asyncio.create_task(
        service.refresh(
            _games(worker_count),
            background=True,
            max_parallelism=worker_count,
        )
    )
    await _wait_for_event_count(rank.events, worker_count)
    await asyncio.sleep(0)
    assert len(rank.events) == worker_count

    for gate in gates.values():
        gate.set()
    result = await task

    assert result.total == TARGET_COUNT
    assert result.success == TARGET_COUNT
    assert result.parallelism == worker_count
    counts = Counter(worker_id for worker_id, _start in rank.events)
    assert max(counts.values()) - min(counts.values()) <= 1


@pytest.mark.asyncio
async def test_scheduled_background_refresh_spreads_page_slots_across_interval(
    monkeypatch: MonkeyPatch,
) -> None:
    targets = _targets(BACKGROUND_TARGET_COUNT)
    rank = _Rank()
    service = _service(
        targets,
        rank,
        monkeypatch,
        interval_minutes=1,
    )
    slots: list[float] = []

    async def record_slot(slot_at: float) -> None:
        slots.append(slot_at)

    monkeypatch.setattr(
        RankPageRefreshService,
        "_wait_for_slot",
        staticmethod(record_slot),
    )
    result = await service.refresh(
        _games(3),
        background=True,
        max_parallelism=3,
    )

    assert result.success == BACKGROUND_TARGET_COUNT
    assert [slot - slots[0] for slot in slots] == pytest.approx(
        [0.0, 20.0, 40.0],
        abs=0.1,
    )


def test_scheduled_background_refresh_adds_bounded_slot_noise(
    monkeypatch: MonkeyPatch,
) -> None:
    targets = _targets(BACKGROUND_TARGET_COUNT)
    rank = _Rank()
    service = _service(
        targets,
        rank,
        monkeypatch,
        interval_minutes=1,
        request_jitter_seconds=5.0,
    )
    jitters = iter((-4.0, 3.0))
    monkeypatch.setattr(
        "ironsbot.services.seer.rank_page_refresh.random.uniform",
        lambda _start, _end: next(jitters),
    )

    slots = service._page_slot_times(
        target_count=BACKGROUND_TARGET_COUNT,
        background=True,
    )

    assert [slot - slots[0] for slot in slots] == pytest.approx(
        [0.0, 16.0, 43.0],
        abs=0.1,
    )


@pytest.mark.asyncio
async def test_manual_refresh_keeps_single_serial_lane(
    monkeypatch: MonkeyPatch,
) -> None:
    targets = _targets(MANUAL_TARGET_COUNT)
    gates = {target.raw_start: asyncio.Event() for target in targets}
    rank = _Rank(gates)
    service = _service(targets, rank, monkeypatch)

    task = asyncio.create_task(service.refresh(_games(2)))
    await _wait_for_event_count(rank.events, 1)
    await asyncio.sleep(0)
    assert len(rank.events) == 1

    for gate in gates.values():
        gate.set()
    result = await task

    assert result.parallelism == 1
    assert result.success == MANUAL_TARGET_COUNT


@pytest.mark.asyncio
async def test_one_failed_page_does_not_back_off_successful_refresh_batch(
    monkeypatch: MonkeyPatch,
) -> None:
    targets = _targets(MANUAL_TARGET_COUNT)
    rank = _Rank(failures={targets[0].raw_start})
    service = _service(targets, rank, monkeypatch)

    result = await service.refresh(_games(1), background=True)

    assert result.success == 1
    assert result.failed == 1
    assert service.backoff_remaining() == 0
