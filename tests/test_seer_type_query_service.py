from __future__ import annotations

import asyncio
from contextlib import contextmanager
from functools import partial
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.integrations.storage.render_cache import FileRenderCache
from ironsbot.services.seer.render_cache import RenderCacheEntry
from ironsbot.services.seer.type_calc import (
    ElementTypeSnapshot,
    TypeCombinationSnapshot,
    TypeMatchup,
    TypeMatchupDataset,
)
from ironsbot.services.seer.type_query import (
    NORMAL_TYPE_MESSAGE,
    TypeQueryService,
    TypeRenderSession,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ironsbot.services.seer.data import SeerDataReader
    from ironsbot.services.seer.type_query import (
        TypeMatchupRenderer,
        TypeRenderSessionFactory,
    )


class FakeData:
    def __init__(self) -> None:
        self.combinations: tuple[Any, ...] = ()
        self.dataset = TypeMatchupDataset((), (), ())
        self.query_open = False
        self.queries = 0

    @contextmanager
    def query(self, _operation: object) -> Iterator[Any]:
        self.queries += 1
        self.query_open = True
        try:
            yield self.combinations if isinstance(_operation, partial) else self.dataset
        finally:
            self.query_open = False


def _type(type_id: int, name: str, *, primary_id: int | None = None) -> Any:
    return SimpleNamespace(
        id=type_id,
        name=name,
        primary_id=type_id if primary_id is None else primary_id,
        secondary_id=None,
    )


def _dataset(target: Any) -> TypeMatchupDataset:
    snapshot = TypeCombinationSnapshot(
        id=int(target.id),
        name=str(target.name),
        primary_id=int(target.primary_id),
        secondary_id=target.secondary_id,
    )
    return TypeMatchupDataset(
        combinations=(snapshot,),
        elements=(ElementTypeSnapshot(snapshot.primary_id, snapshot.name),),
        relations=(),
    )


def _service(
    data: FakeData,
    rendered: list[TypeMatchup] | None = None,
) -> TypeQueryService:
    rendered = [] if rendered is None else rendered

    async def render(matchup: TypeMatchup) -> bytes:
        rendered.append(matchup)
        return b"rendered"

    return TypeQueryService(_render_session(data, render))


def _render_session(
    data: FakeData, render: TypeMatchupRenderer
) -> TypeRenderSessionFactory:
    @contextmanager
    def session() -> Iterator[TypeRenderSession]:
        yield TypeRenderSession(cast("SeerDataReader", data), render, NoCache())

    return session


class NoCache:
    def entry(self, category: str, content_key: str) -> RenderCacheEntry:  # noqa: ARG002
        return RenderCacheEntry(lambda: None, lambda _data: None)


@pytest.mark.asyncio
async def test_single_type_query_renders_matchup() -> None:
    data = FakeData()
    target = _type(1, "草")
    data.combinations = (target,)
    data.dataset = _dataset(target)
    rendered: list[TypeMatchup] = []
    render_session_states: list[bool] = []

    async def render(matchup: TypeMatchup) -> bytes:
        render_session_states.append(data.query_open)
        rendered.append(matchup)
        return b"rendered"

    result = await TypeQueryService(_render_session(data, render)).search("草")

    assert result.reply is not None
    assert result.reply.image == b"rendered"
    assert [item.target for item in rendered] == [
        TypeCombinationSnapshot(1, "草", 1, None)
    ]
    assert render_session_states == [False]


@pytest.mark.asyncio
async def test_normal_type_query_returns_message_without_rendering() -> None:
    data = FakeData()
    data.combinations = (_type(8, "普通"),)

    result = await _service(data).search("普通")

    assert result.message == NORMAL_TYPE_MESSAGE


@pytest.mark.asyncio
async def test_multiple_type_query_returns_choices() -> None:
    data = FakeData()
    data.combinations = (_type(1, "草"), _type(2, "水"))

    result = await _service(data).search("属性")

    assert [(choice.name, choice.value) for choice in result.choices] == [
        ("草", 1),
        ("水", 2),
    ]


@pytest.mark.asyncio
async def test_type_selection_reports_missing_matchup() -> None:
    result = await _service(FakeData()).select(99)

    assert result.message == ("❌未找到属性 99（这是一个bug，请反馈给开发者）")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["search", "select", "custom"])
@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
async def test_matchup_preparation_and_render_share_one_session(
    mode: str, failure: type[BaseException] | None
) -> None:
    global_data = FakeData()
    target = _type(1, "草")
    global_data.combinations = () if mode == "custom" else (target,)
    bound = FakeData()
    bound.combinations = global_data.combinations
    bound.dataset = TypeMatchupDataset(
        combinations=(TypeCombinationSnapshot(1, "草", 1, None),),
        elements=(ElementTypeSnapshot(1, "草"), ElementTypeSnapshot(2, "水")),
        relations=(),
    )
    active = False
    rendered: list[TypeMatchup] = []

    async def render(matchup: TypeMatchup) -> bytes:
        await asyncio.sleep(0)
        assert active
        assert not bound.query_open
        rendered.append(matchup)
        if failure is not None:
            raise failure
        return b"bound"

    @contextmanager
    def session() -> Iterator[TypeRenderSession]:
        nonlocal active
        active = True
        try:
            yield TypeRenderSession(cast("SeerDataReader", bound), render, NoCache())
        finally:
            active = False

    service = TypeQueryService(session)
    request = (
        service.select(1)
        if mode == "select"
        else service.search("草+水" if mode == "custom" else "草")
    )
    if failure is None:
        result = await request
        assert result.reply is not None
        assert result.reply.image == b"bound"
    else:
        with pytest.raises(failure):
            await request
    assert not active
    assert not bound.query_open
    assert len(rendered) == 1
    assert rendered[0].target.primary_id == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["search", "select", "custom"])
@pytest.mark.parametrize("allowed", [False, True])
async def test_query_cache_skips_all_reads_and_is_publication_bound(
    tmp_path: Path, mode: str, *, allowed: bool
) -> None:
    data = FakeData()
    data.combinations = () if mode == "custom" else (_type(1, "草"),)
    data.dataset = TypeMatchupDataset(
        combinations=(TypeCombinationSnapshot(1, "草", 1, None),),
        elements=(ElementTypeSnapshot(1, "草"), ElementTypeSnapshot(2, "水")),
        relations=(),
    )
    cache = FileRenderCache(tmp_path, 1024 * 1024, version_getter=lambda: "unused")
    version = "first"
    calls: list[str] = []

    @contextmanager
    def session() -> Iterator[TypeRenderSession]:
        captured = version

        async def render(matchup: TypeMatchup) -> bytes:
            assert not data.query_open
            calls.append(captured)
            return (captured + matchup.target.name).encode()

        yield TypeRenderSession(
            cast("SeerDataReader", data),
            render,
            cache.bind(captured, lambda _category: allowed),
        )

    service = TypeQueryService(session)

    async def request() -> Any:
        return (
            await service.select(1)
            if mode == "select"
            else await service.search("草+水" if mode == "custom" else "草")
        )

    first = await request()
    queries = data.queries
    second = await request()
    assert second == first
    assert data.queries == queries * (1 if allowed else 2)
    assert calls == ["first"] * (1 if allowed else 2)
    version = "second"
    third = await request()
    assert third != first
    assert calls[-1] == "second"
    queries = data.queries
    version = "first"
    assert await request() == first
    assert data.queries == queries + (0 if allowed else (1 if mode == "select" else 2))


@pytest.mark.asyncio
async def test_custom_query_order_and_failed_render_do_not_poison_cache(
    tmp_path: Path,
) -> None:
    data = FakeData()
    data.dataset = TypeMatchupDataset(
        (), (ElementTypeSnapshot(1, "草"), ElementTypeSnapshot(2, "水")), ()
    )
    cache = FileRenderCache(tmp_path, 1024 * 1024, version_getter=lambda: "release")
    failed = True
    calls: list[str] = []

    async def render(matchup: TypeMatchup) -> bytes:
        calls.append(matchup.target.name)
        if failed:
            raise RuntimeError("render failed")  # noqa: TRY003
        return matchup.target.name.encode()

    @contextmanager
    def session() -> Iterator[TypeRenderSession]:
        yield TypeRenderSession(cast("SeerDataReader", data), render, cache)

    service = TypeQueryService(session)
    with pytest.raises(RuntimeError, match="render failed"):
        await service.search("草+水")
    failed = False
    for arg, title in (("草+水", "草水（DIY 属性）"), ("水+草", "水草（DIY 属性）")):
        result = await service.search(arg)
        assert result.reply is not None and result.reply.image == title.encode()
        queries = data.queries
        assert await service.search(arg) == result
        assert data.queries == queries
    assert calls == ["草水（DIY 属性）", "草水（DIY 属性）", "水草（DIY 属性）"]


def test_type_query_and_calculator_are_render_fingerprint_inputs() -> None:
    from ironsbot.app.rendering_composition import FINAL_RENDER_CACHE_INPUTS

    paths = {path.name for path in FINAL_RENDER_CACHE_INPUTS}
    assert {"type_query.py", "type_calc.py"} <= paths
    assert all(path.exists() for path in FINAL_RENDER_CACHE_INPUTS)
