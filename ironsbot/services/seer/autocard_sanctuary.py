# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ironsbot.core.selection import (
    SelectionMenuItem,
    SelectionMenuSection,
    format_selection_menu,
)

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataAccess

SANCTUARY_QUERY_PREFIXES = (
    "群星牌场地",
    "群星牌圣域",
    "场地",
    "圣域",
    "祝印",
)
SANCTUARY_PROMPT_MAX_ITEMS = 30

_NAME_STRIP_PATTERN = re.compile(r"[\s.·・•‧∙⋅。\-_/]+")
_MISSING_TABLE_MESSAGE = "数据库缺少群星牌场地效果表，请先更新 IronsBot 数据库。"
_EMPTY_DATA_MESSAGE = "数据库没有群星牌场地效果数据，请先更新 IronsBot 数据库。"
_SANCTUARY_EFFECT_QUERY = text(
    """
    SELECT
        effect.id AS effect_id,
        effect.sanctuary_id,
        effect.name AS effect_name,
        effect.description,
        effect.unlock_round,
        effect.stage,
        base.name AS sanctuary_name,
        base.pic_id AS sanctuary_pet_id,
        pet.name AS sanctuary_pet_name
    FROM autocard_season_effect AS effect
    LEFT JOIN autocard_season_effect AS base
      ON base.sanctuary_id = effect.sanctuary_id
     AND base.unlock_round = 0
    LEFT JOIN pet ON pet.id = base.pic_id
    ORDER BY effect.sanctuary_id, effect.unlock_round, effect.id
    """
)


@dataclass(frozen=True, slots=True)
class SanctuaryEffect:
    id: int
    sanctuary_id: int
    name: str
    description: str
    unlock_round: int
    stage: int


@dataclass(frozen=True, slots=True)
class Sanctuary:
    id: int
    name: str
    pet_id: int
    pet_name: str
    effects: tuple[SanctuaryEffect, ...]


@dataclass(frozen=True, slots=True)
class SanctuaryPromptValue:
    kind: Literal["sanctuary", "effect"]
    sanctuary_id: int
    effect_id: int = 0


@dataclass(frozen=True, slots=True)
class SanctuaryEffectEntry:
    id: int
    name: str
    text: str


@dataclass(frozen=True, slots=True)
class SanctuarySearchResult:
    sanctuary: Sanctuary | None = None
    effect: SanctuaryEffectEntry | None = None
    prompt_values: tuple[SanctuaryPromptValue, ...] = ()
    prompt_text: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class _SanctuaryDataset:
    sanctuaries: tuple[Sanctuary, ...]


class AutocardSanctuaryService:
    """Read official element sanctuaries and their round-based blessings."""

    def __init__(self, data: SeerDataAccess) -> None:
        self._data = data

    def search(self, arg: str) -> SanctuarySearchResult:
        query = _extract_query_arg(arg)
        with self._data.query(_load_sanctuary_dataset) as dataset:
            if not query:
                return _sanctuary_menu_result(dataset)
            values = _matching_values(dataset, query)
            if not values:
                return SanctuarySearchResult(
                    message=f"❌ 未找到群星牌场地或祝印：{query}"
                )
            if len(values) == 1:
                return _selection_result(dataset, values[0])
            if len(values) > SANCTUARY_PROMPT_MAX_ITEMS:
                return SanctuarySearchResult(
                    message=(
                        f"❌ 场地或祝印匹配超过 {SANCTUARY_PROMPT_MAX_ITEMS} 个，"
                        "请换更精确的关键词。"
                    )
                )
            return SanctuarySearchResult(
                prompt_values=tuple(values),
                prompt_text=_matching_prompt_text(dataset, values),
            )

    def select(self, value: SanctuaryPromptValue) -> SanctuarySearchResult:
        with self._data.query(_load_sanctuary_dataset) as dataset:
            return _selection_result(dataset, value)


def format_sanctuary_overview(sanctuary: Sanctuary) -> tuple[
    tuple[SanctuaryPromptValue, ...],
    str,
]:
    values = tuple(
        SanctuaryPromptValue("effect", sanctuary.id, effect.id)
        for effect in sanctuary.effects
    )
    sections: list[SelectionMenuSection] = []
    by_round: dict[int, list[SanctuaryEffect]] = {}
    for effect in sanctuary.effects:
        by_round.setdefault(effect.unlock_round, []).append(effect)
    for unlock_round, effects in by_round.items():
        section_name = (
            "基础圣域" if unlock_round == 0 else f"第 {unlock_round} 回合祝印"
        )
        sections.append(
            SelectionMenuSection(
                section_name,
                tuple(SelectionMenuItem(label=effect.name) for effect in effects),
            )
        )
    title = "\n".join(
        (
            "🗺️【群星牌场地】",
            f"场地：{sanctuary.name}（圣域 {sanctuary.id}）",
            f"关联精灵王：{_pet_label(sanctuary)}",
            "输入序号查看完整效果：",
        )
    )
    return values, format_selection_menu(
        title=title,
        items=tuple(sections),
        footer="💬 输入序号查看完整效果",
    )


def _extract_query_arg(arg: str) -> str:
    query = arg.strip()
    for prefix in SANCTUARY_QUERY_PREFIXES:
        if query.casefold().startswith(prefix.casefold()):
            return query[len(prefix) :].strip()
    return query


def _load_sanctuary_dataset(session: Session) -> _SanctuaryDataset:
    try:
        rows = session.execute(_SANCTUARY_EFFECT_QUERY).all()
    except SQLAlchemyError as error:
        raise RuntimeError(_MISSING_TABLE_MESSAGE) from error
    if not rows:
        raise RuntimeError(_EMPTY_DATA_MESSAGE)

    effects_by_sanctuary: dict[int, list[SanctuaryEffect]] = {}
    names: dict[int, str] = {}
    pets: dict[int, tuple[int, str]] = {}
    for row in rows:
        effect = SanctuaryEffect(
            id=_as_int(_row_value(row, "effect_id", 0)),
            sanctuary_id=_as_int(_row_value(row, "sanctuary_id", 1)),
            name=_as_text(_row_value(row, "effect_name", 2)),
            description=_as_text(_row_value(row, "description", 3)),
            unlock_round=_as_int(_row_value(row, "unlock_round", 4)),
            stage=_as_int(_row_value(row, "stage", 5)),
        )
        effects_by_sanctuary.setdefault(effect.sanctuary_id, []).append(effect)
        if sanctuary_name := _as_text(_row_value(row, "sanctuary_name", 6)):
            names[effect.sanctuary_id] = sanctuary_name
        pet_id = _as_int(_row_value(row, "sanctuary_pet_id", 7))
        pet_name = _as_text(_row_value(row, "sanctuary_pet_name", 8))
        if pet_id or pet_name:
            pets[effect.sanctuary_id] = (pet_id, pet_name)

    sanctuaries: list[Sanctuary] = []
    for sanctuary_id, effects in effects_by_sanctuary.items():
        ordered_effects = tuple(
            sorted(effects, key=lambda effect: (effect.unlock_round, effect.id))
        )
        base = next(
            (effect for effect in ordered_effects if effect.unlock_round == 0),
            ordered_effects[0],
        )
        pet_id, pet_name = pets.get(sanctuary_id, (0, ""))
        sanctuaries.append(
            Sanctuary(
                id=sanctuary_id,
                name=names.get(sanctuary_id, base.name),
                pet_id=pet_id,
                pet_name=pet_name,
                effects=ordered_effects,
            )
        )
    return _SanctuaryDataset(
        tuple(sorted(sanctuaries, key=lambda sanctuary: sanctuary.id))
    )


def _row_value(row: object, name: str, index: int) -> object:
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping[name]
    return row[index]  # type: ignore[index]


def _as_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _as_text(value: object) -> str:
    return str(value or "").replace("\\n", "\n").strip()


def _matching_values(
    dataset: _SanctuaryDataset,
    query: str,
) -> list[SanctuaryPromptValue]:
    normalized = _normalize_name(query)
    exact_sanctuaries = [
        sanctuary
        for sanctuary in dataset.sanctuaries
        if normalized
        in {
            _normalize_name(sanctuary.name),
            _normalize_name(sanctuary.pet_name),
        }
    ]
    exact_effects = [
        (sanctuary, effect)
        for sanctuary in dataset.sanctuaries
        for effect in sanctuary.effects
        if effect.unlock_round != 0 and _normalize_name(effect.name) == normalized
    ]
    if exact_sanctuaries or exact_effects:
        return _prompt_values(exact_sanctuaries, exact_effects)

    partial_sanctuaries = [
        sanctuary
        for sanctuary in dataset.sanctuaries
        if normalized in _normalize_name(sanctuary.name)
        or normalized in _normalize_name(sanctuary.pet_name)
    ]
    partial_effects = [
        (sanctuary, effect)
        for sanctuary in dataset.sanctuaries
        for effect in sanctuary.effects
        if effect.unlock_round != 0 and normalized in _normalize_name(effect.name)
    ]
    return _prompt_values(partial_sanctuaries, partial_effects)


def _prompt_values(
    sanctuaries: list[Sanctuary],
    effects: list[tuple[Sanctuary, SanctuaryEffect]],
) -> list[SanctuaryPromptValue]:
    return [
        *(SanctuaryPromptValue("sanctuary", sanctuary.id) for sanctuary in sanctuaries),
        *(
            SanctuaryPromptValue("effect", sanctuary.id, effect.id)
            for sanctuary, effect in effects
        ),
    ]


def _selection_result(
    dataset: _SanctuaryDataset,
    value: SanctuaryPromptValue,
) -> SanctuarySearchResult:
    sanctuary = _find_sanctuary(dataset, value.sanctuary_id)
    if sanctuary is None:
        return SanctuarySearchResult(
            message="❌ 未找到该群星牌场地，这可能是数据库数据已更新或缺失。"
        )
    if value.kind == "sanctuary":
        return SanctuarySearchResult(sanctuary=sanctuary)
    effect = next(
        (effect for effect in sanctuary.effects if effect.id == value.effect_id),
        None,
    )
    if effect is None:
        return SanctuarySearchResult(
            message="❌ 未找到该场地效果，这可能是数据库数据已更新或缺失。"
        )
    return SanctuarySearchResult(effect=_effect_entry(sanctuary, effect))


def _find_sanctuary(
    dataset: _SanctuaryDataset,
    sanctuary_id: int,
) -> Sanctuary | None:
    return next(
        (
            sanctuary
            for sanctuary in dataset.sanctuaries
            if sanctuary.id == sanctuary_id
        ),
        None,
    )


def _sanctuary_menu_result(dataset: _SanctuaryDataset) -> SanctuarySearchResult:
    values = tuple(
        SanctuaryPromptValue("sanctuary", sanctuary.id)
        for sanctuary in dataset.sanctuaries
    )
    return SanctuarySearchResult(
        prompt_values=values,
        prompt_text=format_selection_menu(
            title="🗺️【群星牌场地】请选择要查看的场地：",
            items=tuple(
                SelectionMenuItem(
                    label=(
                        f"{sanctuary.name}（圣域 {sanctuary.id}｜"
                        f"精灵王：{_pet_label(sanctuary)}）"
                    )
                )
                for sanctuary in dataset.sanctuaries
            ),
        ),
    )


def _matching_prompt_text(
    dataset: _SanctuaryDataset,
    values: list[SanctuaryPromptValue],
) -> str:
    return format_selection_menu(
        title="请问你想查询的群星牌场地效果是……",
        items=tuple(
            SelectionMenuItem(label=_prompt_label(dataset, value))
            for value in values
        ),
    )


def _prompt_label(
    dataset: _SanctuaryDataset,
    value: SanctuaryPromptValue,
) -> str:
    sanctuary = _find_sanctuary(dataset, value.sanctuary_id)
    if sanctuary is None:
        return "已失效的场地数据"
    if value.kind == "sanctuary":
        return (
            f"{sanctuary.name}（圣域 {sanctuary.id}｜"
            f"精灵王：{_pet_label(sanctuary)}）"
        )
    effect = next(
        (effect for effect in sanctuary.effects if effect.id == value.effect_id),
        None,
    )
    if effect is None:
        return f"{sanctuary.name}的已失效效果"
    return f"{effect.name}（{sanctuary.name}｜{_phase_name(effect)}）"


def _effect_entry(
    sanctuary: Sanctuary,
    effect: SanctuaryEffect,
) -> SanctuaryEffectEntry:
    return SanctuaryEffectEntry(
        id=effect.id,
        name=effect.name,
        text="\n".join(
            (
                "🗺️【群星牌场地效果】",
                f"场地：{sanctuary.name}（圣域 {sanctuary.id}）",
                f"关联精灵王：{_pet_label(sanctuary)}",
                f"阶段：{_phase_name(effect)}",
                f"效果：{effect.name}（ID：{effect.id}）",
                f"描述：{effect.description or '暂无官方描述'}",
            )
        ),
    )


def _phase_name(effect: SanctuaryEffect) -> str:
    return (
        "基础圣域"
        if effect.unlock_round == 0
        else f"第 {effect.unlock_round} 回合祝印"
    )


def _pet_label(sanctuary: Sanctuary) -> str:
    if sanctuary.pet_id:
        return f"{sanctuary.pet_name or '未收录精灵王'}（{sanctuary.pet_id}）"
    return sanctuary.pet_name or "未关联"


def _normalize_name(value: str) -> str:
    return _NAME_STRIP_PATTERN.sub("", value).casefold()
