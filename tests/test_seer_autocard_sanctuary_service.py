from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy.exc import SQLAlchemyError

from ironsbot.services.seer.autocard_sanctuary import (
    AutocardSanctuaryService,
    SanctuaryPromptValue,
    format_sanctuary_overview,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ironsbot.services.seer.data import SeerDataAccess


_SANCTUARY_ROWS = (
    (8, 2, "沧岚", "商店阶段结束时，锁定精灵牌获得+2/+2", 0, 0, "沧岚", 3105, "沧岚"),
    (9, 2, "潮涌", "锁定的属性加成翻倍", 5, 1, "沧岚", 3105, "沧岚"),
    (11, 2, "碧流", "锁定精灵牌时随机强化精灵", 5, 1, "沧岚", 3105, "沧岚"),
    (12, 2, "惊涛", "锁定的属性加成翻三倍", 10, 2, "沧岚", 3105, "沧岚"),
    (20, 3, "赤炎", "战斗阶段开始时造成火焰伤害", 0, 0, "赤炎", 3301, "炎皇"),
    (21, 3, "潮火", "火焰伤害提高", 5, 1, "赤炎", 3301, "炎皇"),
)


class _Result:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self._rows = rows

    def all(self) -> tuple[tuple[object, ...], ...]:
        return self._rows


class _Session:
    def __init__(self, rows: tuple[tuple[object, ...], ...], *, fails: bool) -> None:
        self._rows = rows
        self._fails = fails

    def execute(self, _query: object) -> _Result:
        if self._fails:
            raise SQLAlchemyError
        return _Result(self._rows)


class _Data:
    def __init__(
        self,
        rows: tuple[tuple[object, ...], ...] = _SANCTUARY_ROWS,
        *,
        fails: bool = False,
    ) -> None:
        self._rows = rows
        self._fails = fails

    @contextmanager
    def query(self, operation: Callable[[Any], Any]) -> Iterator[Any]:
        yield operation(_Session(self._rows, fails=self._fails))


def _service(
    rows: tuple[tuple[object, ...], ...] = _SANCTUARY_ROWS,
    *,
    fails: bool = False,
) -> AutocardSanctuaryService:
    return AutocardSanctuaryService(
        cast("SeerDataAccess", _Data(rows, fails=fails))
    )


def test_bare_sanctuary_command_lists_all_sanctuaries() -> None:
    result = _service().search("场地")

    assert result.prompt_values == (
        SanctuaryPromptValue("sanctuary", 2),
        SanctuaryPromptValue("sanctuary", 3),
    )
    assert "1. 沧岚（圣域 2｜精灵王：沧岚（3105））" in result.prompt_text
    assert "2. 赤炎（圣域 3｜精灵王：炎皇（3301））" in result.prompt_text


def test_sanctuary_overview_groups_effects_and_keeps_details_in_menu() -> None:
    result = _service().search("场地沧岚")

    assert result.sanctuary is not None
    values, overview = format_sanctuary_overview(result.sanctuary)

    assert values == (
        SanctuaryPromptValue("effect", 2, 8),
        SanctuaryPromptValue("effect", 2, 9),
        SanctuaryPromptValue("effect", 2, 11),
        SanctuaryPromptValue("effect", 2, 12),
    )
    assert "场地：沧岚（圣域 2）" in overview
    assert "关联精灵王：沧岚（3105）" in overview
    assert "【基础圣域】\n1. 沧岚" in overview
    assert "【第 5 回合祝印】\n2. 潮涌\n3. 碧流" in overview
    assert "【第 10 回合祝印】\n4. 惊涛" in overview
    assert "锁定的属性加成翻倍" not in overview


@pytest.mark.parametrize(
    ("command", "effect_name"),
    (("场地潮涌", "潮涌"), ("祝印碧流", "碧流")),
)
def test_effect_aliases_return_one_detailed_effect(
    command: str,
    effect_name: str,
) -> None:
    result = _service().search(command)

    assert result.effect is not None
    assert f"效果：{effect_name}" in result.effect.text
    assert "场地：沧岚（圣域 2）" in result.effect.text
    assert "关联精灵王：沧岚（3105）" in result.effect.text
    assert "第 5 回合祝印" in result.effect.text


def test_partial_effect_matches_use_a_contextual_selection_menu() -> None:
    result = _service().search("场地潮")

    assert result.prompt_values == (
        SanctuaryPromptValue("effect", 2, 9),
        SanctuaryPromptValue("effect", 3, 21),
    )
    assert "1. 潮涌（沧岚｜第 5 回合祝印）" in result.prompt_text
    assert "2. 潮火（赤炎｜第 5 回合祝印）" in result.prompt_text


def test_selection_returns_full_effect_description() -> None:
    result = _service().select(SanctuaryPromptValue("effect", 2, 9))

    assert result.effect is not None
    assert "描述：锁定的属性加成翻倍" in result.effect.text


def test_unknown_sanctuary_returns_a_clear_message() -> None:
    assert (
        _service().search("场地不存在").message
        == "❌ 未找到群星牌场地或祝印：不存在"
    )


@pytest.mark.parametrize(
    ("rows", "fails", "expected"),
    (
        ((), False, "数据库没有群星牌场地效果数据"),
        (_SANCTUARY_ROWS, True, "数据库缺少群星牌场地效果表"),
    ),
)
def test_sanctuary_data_errors_are_explicit(
    rows: tuple[tuple[object, ...], ...],
    fails: object,
    expected: str,
) -> None:
    assert isinstance(fails, bool)
    with pytest.raises(RuntimeError, match=expected):
        _service(rows, fails=fails).search("场地")
