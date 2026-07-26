from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.services.seer.equipment import EquipmentQueryService

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource


class FakeData:
    suit = object()
    equip = object()
    title = object()

    def __init__(self) -> None:
        self.values: dict[object, tuple[Any, ...]] = {}
        self.session_active = False

    @contextmanager
    def resolve(
        self,
        getter: object,
        _arg: str,
    ) -> Iterator[tuple[Any, ...]]:
        self.session_active = True
        try:
            yield self.values.get(getter, ())
        finally:
            self.session_active = False

    @contextmanager
    def get(self, getter: object, item_id: int) -> Iterator[Any | None]:
        self.session_active = True
        try:
            yield next(
                (
                    item
                    for item in self.values.get(getter, ())
                    if int(item.id) == item_id
                ),
                None,
            )
        finally:
            self.session_active = False


class FakeImages:
    async def fetch(
        self,
        _kind: object,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        assert fallback is False
        return f"image:{key}".encode()


def _service(data: FakeData) -> EquipmentQueryService:
    return EquipmentQueryService(
        cast("SeerDataAccess", data),
        cast("SeerImageSource", FakeImages()),
    )


class SessionBoundSuit:
    id = 1
    name = "勇者套装"

    def __init__(self, data: FakeData) -> None:
        self._data = data

    @property
    def equips(self) -> list[Any]:
        assert self._data.session_active
        return [
            SimpleNamespace(
                id=11,
                name="头盔",
                part_type=SimpleNamespace(id=0),
                bonus=SimpleNamespace(desc="攻击 + 5"),
            )
        ]

    @property
    def bonus(self) -> Any:
        assert self._data.session_active
        return SimpleNamespace(desc="全属性 + 10")


@pytest.mark.asyncio
async def test_title_query_returns_rendered_reply() -> None:
    data = FakeData()
    data.values[data.title] = (
        SimpleNamespace(
            id=7,
            name="星际英雄",
            ability_desc="体力 + 20",
            achievement=SimpleNamespace(point=10),
        ),
    )

    result = await _service(data).search("title", "星际英雄")

    assert result.reply is not None
    assert result.reply.text == (
        "【星际英雄】\n"
        "🆔：7\n"
        "成就点数：10点\n"
        "效果：体力 + 20"
    )
    assert result.reply.image == b"image:7"


@pytest.mark.asyncio
async def test_title_without_achievement_omits_points() -> None:
    data = FakeData()
    data.values[data.title] = (
        SimpleNamespace(
            id=8,
            name="普通称号",
            ability_desc="",
            achievement=None,
        ),
    )

    result = await _service(data).search("title", "普通称号")

    assert result.reply is not None
    assert result.reply.text == "【普通称号】\n🆔：8"


@pytest.mark.asyncio
async def test_equipment_query_returns_choices_for_multiple_matches() -> None:
    data = FakeData()
    data.values[data.suit] = (
        SimpleNamespace(id=1, name="套装一"),
        SimpleNamespace(id=2, name="套装二"),
    )

    result = await _service(data).search("suit", "套装")

    assert [choice.value for choice in result.choices] == [1, 2]


@pytest.mark.asyncio
async def test_suit_selection_returns_parts_and_bonus() -> None:
    data = FakeData()
    part_type = SimpleNamespace(id=0)
    equip = SimpleNamespace(
        id=11,
        name="头盔",
        part_type=part_type,
        bonus=SimpleNamespace(desc="攻击 + 5"),
    )
    data.values[data.suit] = (
        SimpleNamespace(
            id=1,
            name="勇者套装",
            equips=[equip],
            bonus=SimpleNamespace(desc="全属性 + 10"),
        ),
    )

    result = await _service(data).select("suit", 1)

    assert result.reply is not None
    assert "头部：头盔（11）" in result.reply.text
    assert "套装效果：全属性 + 10" in result.reply.text


@pytest.mark.asyncio
async def test_equipment_formats_relationships_before_session_closes() -> None:
    data = FakeData()
    data.values[data.suit] = (SessionBoundSuit(data),)

    result = await _service(data).select("suit", 1)

    assert result.reply is not None
    assert "头部：头盔（11）" in result.reply.text
    assert data.session_active is False


@pytest.mark.asyncio
async def test_equipment_selection_reports_missing_item() -> None:
    result = await _service(FakeData()).select("equip", 99)

    assert result.message == (
        "❌未找到装备部件 99（这是一个bug，请反馈给开发者）"
    )
