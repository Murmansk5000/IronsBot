from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.services.seer.type_calc import (
    TypeCombinationSnapshot,
    TypeMatchup,
)
from ironsbot.services.seer.type_query import (
    NORMAL_TYPE_MESSAGE,
    TypeQueryService,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.seer.data import SeerDataAccess


class FakeData:
    type_combination = object()

    def __init__(self) -> None:
        self.combinations: tuple[Any, ...] = ()
        self.matchup: TypeMatchup | None = None
        self.query_open = False

    @contextmanager
    def resolve(
        self,
        _getter: object,
        _arg: str,
    ) -> Iterator[tuple[Any, ...]]:
        yield self.combinations

    @contextmanager
    def query(self, _operation: object) -> Iterator[TypeMatchup | None]:
        self.query_open = True
        try:
            yield self.matchup
        finally:
            self.query_open = False


def _type(type_id: int, name: str, *, primary_id: int | None = None) -> Any:
    return SimpleNamespace(
        id=type_id,
        name=name,
        primary_id=type_id if primary_id is None else primary_id,
        secondary_id=None,
    )


def _matchup(target: Any) -> TypeMatchup:
    return TypeMatchup(
        target=TypeCombinationSnapshot(
            id=int(target.id),
            name=str(target.name),
            primary_id=int(target.primary_id),
            secondary_id=target.secondary_id,
        ),
        attack_table=[],
        defense_table=[],
        cache_key=str(target.id),
    )


def _service(
    data: FakeData,
    rendered: list[TypeMatchup] | None = None,
) -> TypeQueryService:
    rendered = [] if rendered is None else rendered

    async def render(matchup: TypeMatchup) -> bytes:
        rendered.append(matchup)
        return b"rendered"

    return TypeQueryService(cast("SeerDataAccess", data), render)


@pytest.mark.asyncio
async def test_single_type_query_renders_matchup() -> None:
    data = FakeData()
    target = _type(1, "草")
    data.combinations = (target,)
    data.matchup = _matchup(target)
    rendered: list[TypeMatchup] = []
    render_session_states: list[bool] = []

    async def render(matchup: TypeMatchup) -> bytes:
        render_session_states.append(data.query_open)
        rendered.append(matchup)
        return b"rendered"

    result = await TypeQueryService(cast("SeerDataAccess", data), render).search(
        "草"
    )

    assert result.reply is not None
    assert result.reply.image == b"rendered"
    assert rendered == [data.matchup]
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

    assert result.message == (
        "❌未找到属性 99（这是一个bug，请反馈给开发者）"
    )
