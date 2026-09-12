from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy import event as sql_event
from sqlmodel import Session, SQLModel, create_engine

from ironsbot.core import time
from ironsbot.integrations.seer_data.peak_repository import (
    PeakPeriodTimes,
    load_peak_pet_snapshots,
    load_peak_pool_snapshots,
    load_peak_vote_snapshots,
)
from ironsbot.services.operations.headless_errors import DisconnectedError
from ironsbot.services.seer import peak
from ironsbot.services.seer.images import ImageSourceError
from ironsbot.services.seer.peak import (
    PeakItemData,
    PeakPetSnapshot,
    PeakPoolSnapshot,
    PeakQueryService,
    PeakRenderSession,
    active_peak_pool_limits,
)
from ironsbot.services.seer.render_coordinator import RenderCoordinator
from ironsbot.services.seer.render_paths import PEAK_POOL_VOTE_TEMPLATE_PATH

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest import MonkeyPatch

    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.data import SeerDataAccess, SeerDataReader
    from ironsbot.services.seer.peak import (
        PeakPetRenderer,
        PeakPoolRenderer,
        PeakRenderSessionFactory,
        PeakVoteRenderer,
    )
    from ironsbot.services.seer.rank_models import RankEntry


class FakeData:
    suit = object()
    title = object()
    pet = object()

    def __init__(self) -> None:
        self.query_result: Any = None
        self.query_results: list[Any] = []
        self.models: dict[int, Any] = {}
        self.query_open = False
        self.render_open = False
        self.get_many_open = False

    @contextmanager
    def query(self, _operation: object) -> Iterator[Any]:
        self.query_open = True
        try:
            yield self.query_results.pop(0) if self.query_results else self.query_result
        finally:
            self.query_open = False

    @contextmanager
    def get_many(
        self,
        _getter: object,
        _ids: set[int],
    ) -> Iterator[dict[int, Any]]:
        self.get_many_open = True
        try:
            yield self.models
        finally:
            self.get_many_open = False


class FakeHeadless:
    def __init__(self, game: Any = None, error: Exception | None = None) -> None:
        self.game = game
        self.error = error

    def get_game(self) -> Any:
        if self.error is not None:
            raise self.error
        return self.game


def _pool_snapshot() -> PeakPoolSnapshot:
    return PeakPoolSnapshot(
        id=1,
        count=2,
        start_time=datetime(2026, 7, 1, tzinfo=time.TZ_CN),
        end_time=datetime(2026, 7, 31, tzinfo=time.TZ_CN),
        pets=(),
    )


def _vote_snapshot(
    vote_id: int,
    subkey: int,
    start_time: datetime,
    end_time: datetime,
    pets: tuple[PeakPetSnapshot, ...] = (),
) -> peak.PeakVoteSnapshot:
    return peak.PeakVoteSnapshot(
        id=vote_id,
        count=2,
        subkey=subkey,
        start_time=start_time,
        end_time=end_time,
        pets=pets,
    )


def test_active_peak_pool_limits_uses_only_current_pools_and_strictest_limit() -> None:
    current_time = datetime(2026, 7, 22, tzinfo=time.TZ_CN)
    pet_one = PeakPetSnapshot(id=1, name="One", resource_id=1, type_id=1)
    pet_two = PeakPetSnapshot(id=2, name="Two", resource_id=2, type_id=1)

    limits = active_peak_pool_limits(
        (
            PeakPoolSnapshot(
                id=1,
                count=3,
                start_time=datetime(2026, 7, 1, tzinfo=time.TZ_CN),
                end_time=datetime(2026, 7, 31, tzinfo=time.TZ_CN),
                pets=(pet_one, pet_two),
            ),
            PeakPoolSnapshot(
                id=2,
                count=2,
                start_time=datetime(2026, 7, 10, tzinfo=time.TZ_CN),
                end_time=datetime(2026, 7, 25, tzinfo=time.TZ_CN),
                pets=(pet_one,),
            ),
            PeakPoolSnapshot(
                id=3,
                count=0,
                start_time=datetime(2026, 6, 1, tzinfo=time.TZ_CN),
                end_time=datetime(2026, 6, 30, tzinfo=time.TZ_CN),
                pets=(pet_two,),
            ),
        ),
        at=current_time,
    )

    assert limits == {1: 2, 2: 3}


def test_peak_pet_repository_returns_only_requested_detached_fields() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    statements: list[str] = []

    def track_sql(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    sql_event.listen(engine, "before_cursor_execute", track_sql)
    try:
        with Session(engine) as session:
            session.execute(
                SQLModel.metadata.tables["element_type_combination"].insert(),
                [
                    {
                        "id": 4,
                        "name": "type",
                        "name_en": "type",
                        "primary_id": 4,
                    }
                ],
            )
            session.execute(
                SQLModel.metadata.tables["pet"].insert(),
                [
                    {
                        "id": pet_id,
                        "name": "pet",
                        "yielding_exp": 0,
                        "catch_rate": 0,
                        "releaseable": False,
                        "fusion_master": False,
                        "fusion_sub": False,
                        "has_resistance": False,
                        "resource_id": 1007,
                        "type_id": 4,
                        "gender_id": 0,
                        "base_stats_id": 0,
                        "yielding_ev_id": 0,
                    }
                    for pet_id in (7, 9)
                ],
            )
            session.commit()
            statements.clear()
            assert load_peak_pet_snapshots(session, set()) == {}
            pets = load_peak_pet_snapshots(session, {7, 99})
            assert len(statements) == 1
    finally:
        engine.dispose()
    assert pets == {7: PeakPetSnapshot(7, "pet", 1007, 4)}


@pytest.mark.parametrize("table", ["peak_pool", "peak_expert_pool", "peak_pool_vote"])
def test_peak_repository_batches_pool_members_without_loading_types(table: str) -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    statements: list[str] = []

    def track_sql(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    sql_event.listen(engine, "before_cursor_execute", track_sql)
    pool_count = 5
    start = datetime(2026, 7, 1, tzinfo=time.TZ_CN)
    end = datetime(2026, 7, 31, tzinfo=time.TZ_CN)
    try:
        with Session(engine) as session:
            session.execute(
                SQLModel.metadata.tables[table].insert(),
                [
                    {
                        "id": index,
                        "count": 2,
                        "start_time": start,
                        "end_time": end,
                        **({"subkey": index} if table == "peak_pool_vote" else {}),
                    }
                    for index in range(pool_count)
                ],
            )
            session.execute(
                SQLModel.metadata.tables["element_type_combination"].insert(),
                [
                    {
                        "id": index,
                        "name": "type",
                        "name_en": "type",
                        "primary_id": index,
                    }
                    for index in range(pool_count)
                ],
            )
            session.execute(
                SQLModel.metadata.tables["pet"].insert(),
                [
                    {
                        "id": index,
                        "name": "pet",
                        "yielding_exp": 0,
                        "catch_rate": 0,
                        "releaseable": False,
                        "fusion_master": False,
                        "fusion_sub": False,
                        "has_resistance": False,
                        "resource_id": index + 1000,
                        "type_id": index,
                        "gender_id": 0,
                        "base_stats_id": 0,
                        "yielding_ev_id": 0,
                        f"{table}_id": index,
                    }
                    for index in range(pool_count)
                ],
            )
            session.commit()
            statements.clear()
            pools = (
                load_peak_vote_snapshots(session)
                if table == "peak_pool_vote"
                else load_peak_pool_snapshots(
                    session, expert=table == "peak_expert_pool"
                )
            )
            expected_queries = 2
            assert len(statements) == expected_queries
            assert not any("element_type_combination" in sql for sql in statements)
        assert len(pools) == pool_count
        assert {pool.id: pool.pets for pool in pools} == {
            index: (PeakPetSnapshot(index, "pet", index + 1000, index),)
            for index in range(pool_count)
        }
    finally:
        engine.dispose()


def _render_session(
    data: FakeData,
    pool: PeakPoolRenderer,
    vote: PeakVoteRenderer,
    pet: PeakPetRenderer,
) -> PeakRenderSessionFactory:
    @contextmanager
    def session() -> Iterator[PeakRenderSession]:
        data.render_open = True
        try:
            yield PeakRenderSession(cast("SeerDataReader", data), pool, vote, pet)
        finally:
            data.render_open = False

    return session


def _service(
    data: FakeData,
    headless: FakeHeadless,
    rendered: dict[str, Any],
    *,
    global_data: FakeData | None = None,
) -> PeakQueryService:
    async def render_pool(pools: Any, title: str) -> bytes:
        assert data.render_open
        rendered["pool"] = (pools, title)
        rendered["pool_session_open"] = data.query_open
        return b"pool"

    async def render_vote(pools: Any, generated_at: str) -> bytes:
        assert data.render_open
        rendered["vote"] = pools
        rendered["vote_generated_at"] = generated_at
        rendered["vote_session_open"] = data.query_open
        return b"vote"

    async def render_pet(input_: Any) -> bytes:
        assert data.render_open
        assert not data.query_open
        rendered["pet"] = input_
        return b"pet"

    return PeakQueryService(
        cast("SeerDataAccess", global_data if global_data is not None else data),
        cast("HeadlessService", headless),
        _render_session(data, render_pool, render_vote, render_pet),
    )


@pytest.mark.asyncio
async def test_peak_pool_query_renders_with_progress() -> None:
    data = FakeData()
    data.query_result = (_pool_snapshot(),)
    rendered: dict[str, Any] = {}
    progress: list[str] = []

    async def report(message: str) -> None:
        progress.append(message)

    result = await _service(data, FakeHeadless(), rendered).pool(
        expert=False,
        progress=report,
    )

    assert result.image == b"pool"
    assert progress == ["正在生成图片..."]
    assert rendered["pool_session_open"] is False
    assert rendered["pool"][1] == "竞技池 / 2026-07-01 ~ 2026-07-31"
    assert rendered["pool"][0] == (
        PeakPoolSnapshot(
            id=1,
            count=2,
            start_time=datetime(2026, 7, 1, tzinfo=time.TZ_CN),
            end_time=datetime(2026, 7, 31, tzinfo=time.TZ_CN),
            pets=(),
        ),
    )


@pytest.mark.asyncio
async def test_peak_pet_rank_snapshots_pets_before_rendering(
    monkeypatch: MonkeyPatch,
) -> None:
    current_time = datetime(2026, 9, 12, 14, 0, tzinfo=time.TZ_CN)
    monkeypatch.setattr(peak.time, "now", lambda *, tz: current_time.astimezone(tz))
    data = FakeData()
    data.query_result = PeakPeriodTimes(
        start_time=datetime(2026, 7, 1, tzinfo=time.TZ_CN),
        end_time=datetime(2026, 7, 31, tzinfo=time.TZ_CN),
    )
    data.models = {
        7: SimpleNamespace(
            id=7,
            name="雷伊",
            resource_id=1007,
            type=SimpleNamespace(id=4),
        )
    }
    rendered: dict[str, Any] = {}

    class FakeGame:
        async def get_peak_pet_rank(
            self,
            _sub_key: int,
            _peak_type: object,
        ) -> tuple[list[PeakItemData], list[RankEntry]]:
            return [PeakItemData(id=7, count=10, win=6)], []

    async def report(_message: str) -> None:
        nonlocal current_time
        current_time = datetime(2026, 9, 12, 14, 1, tzinfo=time.TZ_CN)

    data.query_results = [data.query_result, {7: PeakPetSnapshot(7, "雷伊", 1007, 4)}]
    service = _service(data, FakeHeadless(FakeGame()), rendered)
    result = await service.pet_rank("竞技精灵总榜", report)

    assert result.image == b"pet"
    assert rendered["pet"].observed_at == "2026-09-12 14:00:00"
    assert data.get_many_open is False
    assert rendered["pet"].pets == (
        PeakPetSnapshot(
            id=7,
            name="雷伊",
            resource_id=1007,
            type_id=4,
        ),
    )


@pytest.mark.asyncio
async def test_peak_vote_snapshots_pets_before_headless_requests(
    monkeypatch: MonkeyPatch,
) -> None:
    current_time = datetime(2026, 7, 20, 19, 0, tzinfo=time.TZ_CN)
    monkeypatch.setattr(peak.time, "now", lambda *, tz: current_time.astimezone(tz))
    data = FakeData()
    data.query_result = (
        _vote_snapshot(
            1,
            99,
            datetime(2026, 7, 1, tzinfo=time.TZ_CN),
            datetime(2026, 7, 31, tzinfo=time.TZ_CN),
            (PeakPetSnapshot(7, "雷伊", 1007, 4),),
        ),
    )
    rendered: dict[str, Any] = {}

    class FakeGame:
        async def get_limit_pool_vote(self, _sub_key: int) -> list[RankEntry]:
            return []

    async def report(_message: str) -> None:
        return None

    result = await _service(data, FakeHeadless(FakeGame()), rendered).vote(report)

    assert result.image == b"vote"
    assert rendered["vote_session_open"] is False
    assert rendered["vote"][0].pets == (
        PeakPetSnapshot(
            id=7,
            name="雷伊",
            resource_id=1007,
            type_id=4,
        ),
    )


@pytest.mark.asyncio
async def test_peak_vote_fetches_only_active_pools(
    monkeypatch: MonkeyPatch,
) -> None:
    current_time = datetime(2026, 7, 20, 19, 0, tzinfo=time.TZ_CN)
    monkeypatch.setattr(peak.time, "now", lambda *, tz: current_time.astimezone(tz))

    data = FakeData()
    data.query_result = (
        _vote_snapshot(
            1,
            101,
            datetime(2026, 7, 1, tzinfo=time.TZ_CN),
            datetime(2026, 7, 2, tzinfo=time.TZ_CN),
        ),
        _vote_snapshot(
            2,
            202,
            datetime(2026, 7, 20, 18, tzinfo=time.TZ_CN),
            datetime(2026, 7, 20, 20, tzinfo=time.TZ_CN),
        ),
        _vote_snapshot(
            3,
            303,
            datetime(2026, 7, 21, tzinfo=time.TZ_CN),
            datetime(2026, 7, 22, tzinfo=time.TZ_CN),
        ),
    )
    called_subkeys: list[int] = []
    rendered: dict[str, Any] = {}

    class FakeGame:
        async def get_limit_pool_vote(self, sub_key: int) -> list[RankEntry]:
            called_subkeys.append(sub_key)
            return []

    async def report(_message: str) -> None:
        return None

    result = await _service(data, FakeHeadless(FakeGame()), rendered).vote(report)

    assert result.image == b"vote"
    assert called_subkeys == [202]
    assert len(rendered["vote"]) == 1


@pytest.mark.asyncio
async def test_peak_vote_reports_render_timeout(
    monkeypatch: MonkeyPatch,
) -> None:
    current_time = datetime(2026, 7, 20, 19, 0, tzinfo=time.TZ_CN)
    monkeypatch.setattr(peak.time, "now", lambda *, tz: current_time.astimezone(tz))

    data = FakeData()
    data.query_result = (
        _vote_snapshot(
            1,
            101,
            datetime(2026, 7, 20, 18, tzinfo=time.TZ_CN),
            datetime(2026, 7, 20, 20, tzinfo=time.TZ_CN),
        ),
    )

    class FakeGame:
        async def get_limit_pool_vote(self, _sub_key: int) -> list[RankEntry]:
            return []

    async def render_html(*_args: Any, **_kwargs: Any) -> bytes:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    coordinator = RenderCoordinator(render_html, timeout_seconds=0.01)

    async def render_vote(_pools: tuple[Any, ...], _generated_at: str) -> bytes:
        return await coordinator.render(PEAK_POOL_VOTE_TEMPLATE_PATH, "unused", {})

    async def render_pool(_pools: Any, _title: str) -> bytes:
        return b"pool"

    async def render_pet(_input: Any) -> bytes:
        return b"pet"

    async def report(_message: str) -> None:
        return None

    service = PeakQueryService(
        cast("SeerDataAccess", data),
        cast("HeadlessService", FakeHeadless(FakeGame())),
        _render_session(data, render_pool, render_vote, render_pet),
    )

    result = await service.vote(report)

    assert result.message == "❌巅峰投票图片生成超时，请稍后再试。"
    assert not data.render_open


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["pool", "vote", "pet"])
@pytest.mark.parametrize(
    "failure", [ImageSourceError, TimeoutError, RuntimeError, asyncio.CancelledError]
)
async def test_peak_render_failure_and_recovery(
    monkeypatch: MonkeyPatch, mode: str, failure: type[BaseException]
) -> None:
    now = datetime(2026, 7, 20, tzinfo=time.TZ_CN)
    monkeypatch.setattr(peak.time, "now", lambda *, tz: now.astimezone(tz))
    data = FakeData()
    pool = _pool_snapshot()
    data.query_result = (
        (_vote_snapshot(1, 99, pool.start_time, pool.end_time),)
        if mode == "vote"
        else (pool,)
    )

    class Game:
        async def get_limit_pool_vote(self, _sub_key: int) -> list[RankEntry]:
            return []

        async def get_peak_pet_rank(
            self, _sub_key: int, _peak_type: object
        ) -> tuple[list[PeakItemData], list[RankEntry]]:
            return [PeakItemData(7, 10, 6)], []

    broken = True
    calls = 0

    async def render(*_args: Any) -> bytes:
        nonlocal calls
        calls += 1
        assert data.render_open and not data.query_open
        if broken:
            raise failure
        return b"recovered"

    async def report(_message: str) -> None:
        assert not data.query_open

    service = PeakQueryService(
        cast("SeerDataAccess", data),
        cast("HeadlessService", FakeHeadless(Game())),
        _render_session(data, render, render, render),
    )

    async def request() -> peak.PeakQueryResult:
        if mode == "vote":
            return await service.vote(report)
        if mode == "pet":
            data.query_results = [
                PeakPeriodTimes(pool.start_time, pool.end_time),
                {7: PeakPetSnapshot(7, "pet", 70, 1)},
            ]
            return await service.pet_rank("竞技精灵总榜", report)
        return await service.pool(expert=False, progress=report)

    if failure in {RuntimeError, asyncio.CancelledError}:
        with pytest.raises(failure):
            await request()
    else:
        failed = await request()
        assert failed.image is None
        assert (
            "素材获取失败" if failure is ImageSourceError else "生成超时"
        ) in failed.message
        assert {"pool": "竞技池", "vote": "巅峰投票", "pet": "竞技精灵总榜"}[
            mode
        ] in failed.message
    assert not data.render_open and not data.query_open
    failed_calls = calls
    broken = False
    recovered = await request()
    assert recovered.image == b"recovered"
    assert recovered.message == ""
    assert calls == failed_calls + 1
    assert not data.render_open and not data.query_open


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["pool", "expert", "vote", "pet"])
@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
async def test_peak_rendering_uses_bound_reader_until_completion(
    monkeypatch: MonkeyPatch, mode: str, failure: type[BaseException] | None
) -> None:
    now = datetime(2026, 7, 20, tzinfo=time.TZ_CN)
    monkeypatch.setattr(peak.time, "now", lambda *, tz: now.astimezone(tz))
    data = FakeData()
    pool = _pool_snapshot()
    data.query_result = {
        "pool": (pool,),
        "expert": (pool,),
        "vote": (_vote_snapshot(1, 99, pool.start_time, pool.end_time),),
        "pet": None,
    }[mode]
    data.query_results = (
        [
            PeakPeriodTimes(pool.start_time, pool.end_time),
            {7: PeakPetSnapshot(7, "bound", 1007, 4)},
        ]
        if mode == "pet"
        else []
    )

    class Game:
        async def get_limit_pool_vote(self, _sub_key: int) -> list[RankEntry]:
            assert data.render_open and not data.query_open
            await asyncio.sleep(0)
            return []

        async def get_peak_pet_rank(
            self, _sub_key: int, _peak_type: object
        ) -> tuple[list[PeakItemData], list[RankEntry]]:
            assert data.render_open and not data.query_open
            await asyncio.sleep(0)
            return [PeakItemData(7, 10, 6)], []

    async def report(_message: str) -> None:
        assert data.render_open and not data.query_open
        await asyncio.sleep(0)
        if failure is not None:
            raise failure

    rendered: dict[str, Any] = {}
    service = _service(data, FakeHeadless(Game()), rendered, global_data=FakeData())
    if mode == "vote":
        request = service.vote(report)
    elif mode == "pet":
        request = service.pet_rank("竞技精灵总榜", report)
    else:
        request = service.pool(expert=mode == "expert", progress=report)
    if failure is not None:
        with pytest.raises(failure):
            await request
    else:
        result = await request
        assert result.image is not None
        if mode == "pet":
            assert rendered["pet"].pets == (PeakPetSnapshot(7, "bound", 1007, 4),)
    assert not data.render_open
    assert not data.query_open


@pytest.mark.asyncio
async def test_peak_query_reports_disconnected_headless_client() -> None:
    service = _service(
        FakeData(),
        FakeHeadless(error=DisconnectedError()),
        {},
    )

    result = await service.item_rank("竞技套装榜", kind="套装")

    assert result.message == ("❌ 无头客户端连接已断开，正在尝试重连，请稍后再试")


@pytest.mark.asyncio
async def test_peak_item_rank_formats_game_results(
    monkeypatch: MonkeyPatch,
) -> None:
    data = FakeData()
    data.query_result = PeakPeriodTimes(
        start_time=datetime(2026, 7, 1, tzinfo=time.TZ_CN),
        end_time=datetime(2026, 7, 31, tzinfo=time.TZ_CN),
    )
    data.models = {7: SimpleNamespace(name="勇者套装")}

    class FakeGame:
        async def get_peak_suit_rank(
            self,
            _sub_key: int,
            _peak_type: object,
        ) -> list[PeakItemData]:
            return [PeakItemData(id=7, count=10, win=6)]

    now = datetime(2026, 7, 19, 12, 0, tzinfo=time.TZ_CN)
    monkeypatch.setattr(time, "now", lambda *, tz: now.astimezone(tz))
    result = await _service(
        data,
        FakeHeadless(FakeGame()),
        {},
    ).item_rank("竞技套装榜", kind="套装")

    assert result.text == (
        "竞技套装榜（截至2026-07-19 12:00:00）\n"
        "1. 勇者套装 | 出场 10 | 胜场 6 | 胜率 60.0%"
    )
