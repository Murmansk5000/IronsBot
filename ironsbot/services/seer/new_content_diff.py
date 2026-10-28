# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed, escaped-at-template-boundary presentation of published field changes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import zip_longest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.services.seer.new_content import NewContentItem
    from ironsbot.services.seer.rendering.custom_pet_models import SkillDict

_LABELS = {
    "name": "名称",
    "description": "效果说明",
    "info": "技能说明",
    "desc": "效果说明",
    "stats": "属性数值",
    "power": "威力",
    "max_pp": "PP",
    "accuracy": "命中",
    "priority": "先制",
    "hp": "体力",
    "atk": "攻击",
    "def": "防御",
    "def_": "防御",
    "sp_atk": "特攻",
    "sp_def": "特防",
    "spd": "速度",
    "skills": "技能",
    "skill": "技能",
    "effects": "效果",
    "skill_effect": "技能效果",
    "skill_text": "技能效果",
    "skill_upgrade": "升级效果",
    "rarity": "档位",
    "quality": "品质",
    "category": "类别",
    "type_id": "属性",
    "bonus": "效果",
    "suit_desc": "套装说明",
    "learning_level": "学习等级",
    "must_hit": "必中",
    "crit_rate": "暴击率",
}


@dataclass(frozen=True, slots=True)
class DiffFragment:
    text: str
    changed: bool = False


@dataclass(frozen=True, slots=True)
class DiffLine:
    old: tuple[DiffFragment, ...]
    new: tuple[DiffFragment, ...]


@dataclass(frozen=True, slots=True)
class FieldDiff:
    label: str
    lines: tuple[DiffLine, ...]


def _text(value: object) -> str:
    if isinstance(value, str):
        return value or "（空文本）"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _fragments(old: str, new: str) -> DiffLine:
    before: list[DiffFragment] = []
    after: list[DiffFragment] = []
    for operation, a, b, c, d in SequenceMatcher(
        None, old, new, autojunk=False
    ).get_opcodes():
        if a != b:
            before.append(DiffFragment(old[a:b], operation != "equal"))
        if c != d:
            after.append(DiffFragment(new[c:d], operation != "equal"))
    return DiffLine(tuple(before), tuple(after))


def _lines(old: str, new: str) -> tuple[DiffLine, ...]:
    result: list[DiffLine] = []
    before, after = old.splitlines(), new.splitlines()
    for operation, a, b, c, d in SequenceMatcher(
        None, before, after, autojunk=False
    ).get_opcodes():
        for left, right in zip_longest(before[a:b], after[c:d], fillvalue=""):
            if operation == "equal":
                result.append(DiffLine((DiffFragment(left),), (DiffFragment(right),)))
            else:
                result.append(_fragments(left, right))
    return tuple(result)


def present_field_changes(item: NewContentItem) -> tuple[tuple[FieldDiff, ...], str]:
    if item.change_kind != "modified" or item.category.startswith("peak_"):
        return (), ""
    values = item.payload.get("field_changes")
    if item.payload.get("field_changes_version") != 1 or not isinstance(values, list):
        return (), "旧值未提供，无法对比"
    fields: list[FieldDiff] = []
    incomplete = False
    for value in values:
        if not _valid_change(value):
            incomplete = True
            continue
        old_exists, new_exists = value["old_exists"], value["new_exists"]
        old = _text(value["old"]) if old_exists else "（字段不存在）"
        new = _text(value["new"]) if new_exists else "（字段不存在）"
        if (
            old_exists == new_exists
            and type(value.get("old")) is type(value.get("new"))
            and value.get("old") == value.get("new")
        ):
            continue
        if old == new:
            if isinstance(value.get("old"), str):
                old += "（文本）"
            if isinstance(value.get("new"), str):
                new += "（文本）"
        path = value["path"]
        label = " / ".join(
            f"ID {part[3:]}" if part.startswith("id=") else str(_LABELS.get(part, part))
            for part in path
            if part != "payload"
        )
        fields.append(FieldDiff(label or "内容", _lines(old, new)))
    return tuple(fields), "部分旧值未提供，无法完整对比" if incomplete else ""


def _valid_change(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    path = value.get("path")
    return (
        isinstance(path, list)
        and all(isinstance(part, str) for part in path)
        and type(value.get("old_exists")) is bool
        and type(value.get("new_exists")) is bool
        and (not value["old_exists"] or "old" in value)
        and (not value["new_exists"] or "new" in value)
    )


def compared_text_values(item: NewContentItem) -> frozenset[str]:
    """Only suppress current text when its complete value appears in the diff."""
    if item.payload.get("field_changes_version") != 1:
        return frozenset()
    values = item.payload.get("field_changes")
    if not isinstance(values, list):
        return frozenset()
    return frozenset(
        value["new"].strip()
        for value in values
        if _valid_change(value)
        and value["new_exists"]
        and isinstance(value.get("new"), str)
    )


def without_compared_skill_text(
    skill: SkillDict | None, compared: frozenset[str]
) -> SkillDict | None:
    if skill is None or not compared:
        return skill
    result = skill.copy()
    if (result["info"] or "").strip() in compared:
        result["info"] = None
    if (result["hide_effect_desc"] or "").strip() in compared:
        result["hide_effect_desc"] = None
    result["effects"] = [
        effect
        for effect in result["effects"]
        if str(effect.get("info", "")).strip() not in compared
    ]
    return result
