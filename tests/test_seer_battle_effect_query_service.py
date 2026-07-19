from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.services.seer.battle_effect import BattleEffectQueryService

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource


class FakeData:
    battle_effect = object()

    def __init__(self) -> None:
        self.effects: tuple[Any, ...] = ()

    @contextmanager
    def resolve(
        self,
        _getter: object,
        _arg: str,
    ) -> Iterator[tuple[Any, ...]]:
        yield self.effects

    @contextmanager
    def get(
        self,
        _getter: object,
        effect_id: int,
    ) -> Iterator[Any | None]:
        yield next(
            (effect for effect in self.effects if effect.id == effect_id),
            None,
        )


class FakeImages:
    async def fetch(
        self,
        kind: object,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        assert kind == "battle_effect"
        assert fallback is False
        return f"image:{key}".encode()


def _effect(effect_id: int, name: str) -> Any:
    return SimpleNamespace(
        id=effect_id,
        name=name,
        type=[SimpleNamespace(name="控制")],
        resistance=SimpleNamespace(name="害怕"),
        desc="无法行动",
    )


def _service(data: FakeData) -> BattleEffectQueryService:
    return BattleEffectQueryService(
        cast("SeerDataAccess", data),
        cast("SeerImageSource", FakeImages()),
    )


@pytest.mark.asyncio
async def test_single_battle_effect_returns_formatted_reply() -> None:
    data = FakeData()
    data.effects = (_effect(1, "害怕"),)

    result = await _service(data).search("害怕")

    assert result.reply is not None
    assert result.reply.image == b"image:1"
    assert result.reply.text == (
        "【害怕（ID：1）】\n"
        "类型：控制\n"
        "抗性类型：害怕\n"
        "效果：无法行动"
    )


@pytest.mark.asyncio
async def test_multiple_battle_effects_return_choices() -> None:
    data = FakeData()
    data.effects = (_effect(1, "害怕"), _effect(2, "疲惫"))

    result = await _service(data).search("异常")

    assert [(choice.name, choice.value) for choice in result.choices] == [
        ("害怕", 1),
        ("疲惫", 2),
    ]


@pytest.mark.asyncio
async def test_battle_effect_selection_reports_missing_item() -> None:
    result = await _service(FakeData()).select(99)

    assert result.message == (
        "❌未找到异常状态 99（这是一个bug，请反馈给开发者）"
    )
