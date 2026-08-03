# SPDX-License-Identifier: GPL-3.0-or-later
"""Skill-card details used by the weekly new-content renderer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from seerapi_models import SkillORM

from .analyze_description import (
    format_analyze_description,
    format_plain_analyze_description,
)
from .custom_pet_models import SkillDict

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.new_content import NewContentItem


@dataclass(frozen=True, slots=True)
class NewContentItemDetails:
    metadata: str
    description: str
    side_title: str = ""
    side_description: str = ""
    stats: tuple[tuple[str, str], ...] = ()
    stats_layout: str = "inline"
    stats_total: str = ""
    type_id: int | None = None
    gender_id: int | None = None
    type_name: str = ""
    gender_name: str = ""
    skill: SkillDict | None = None
    friend_skill: SkillDict | None = None


@dataclass(frozen=True, slots=True)
class _SkillEffectDetails:
    effects: list[dict[str, Any]]
    friend_effects: list[dict[str, Any]]
    hide_effect_desc: str | None


SKILL_CATEGORY_ATTRIBUTE = 4
_SKILL_CATEGORY_NAMES = {
    1: "物理攻击",
    2: "特殊攻击",
    SKILL_CATEGORY_ATTRIBUTE: "属性技能",
}


def load_new_content_skill_details(
    data: SeerDataAccess,
    item: NewContentItem,
) -> NewContentItemDetails:
    payload = item.payload
    type_id = _payload_int(payload, "type_id")
    type_name = ""
    if type_id > 0:
        with data.get(data.type_combination, type_id) as skill_type:
            if skill_type is not None:
                type_name = str(skill_type.name)
    category_id = _payload_int(payload, "category_id")
    must_hit = bool(payload.get("must_hit", False))
    raw_crit_rate = payload.get("crit_rate")
    crit_rate = (
        _payload_int(payload, "crit_rate")
        if isinstance(raw_crit_rate, int | float | str)
        else None
    )
    effect_details = _load_skill_effect_details(data, item.entity_id)
    skill = SkillDict(
        id=item.entity_id,
        name=item.name,
        type_id=type_id,
        type_name=type_name,
        category_id=category_id,
        category_name=_SKILL_CATEGORY_NAMES.get(category_id, "未知分类"),
        power=_payload_int(payload, "power"),
        max_pp=_payload_int(payload, "max_pp"),
        accuracy="必中" if must_hit else _payload_int(payload, "accuracy"),
        crit_rate=crit_rate,
        priority=_payload_int(payload, "priority"),
        must_hit=must_hit,
        info=format_plain_analyze_description(
            str(payload.get("info", "")).strip() or None
        ),
        learning_level=None,
        is_special=False,
        is_advanced=False,
        is_fifth=False,
        effects=effect_details.effects,
        activation_item=None,
        friend_bonus=False,
        hide_effect_desc=effect_details.hide_effect_desc,
    )
    friend_skill: SkillDict | None = None
    if effect_details.friend_effects:
        friend_skill = {
            **skill,
            "effects": effect_details.friend_effects,
            "friend_bonus": True,
            "is_special": True,
        }
    return NewContentItemDetails(
        metadata="",
        description=_skill_related_pets(payload.get("pets")),
        type_id=type_id or None,
        type_name=type_name,
        skill=skill,
        friend_skill=friend_skill,
    )


def _load_skill_effect_details(
    data: SeerDataAccess,
    skill_id: int,
) -> _SkillEffectDetails:
    try:
        with data.query(lambda session: session.get(SkillORM, skill_id)) as skill:
            if skill is None:
                return _SkillEffectDetails([], [], None)
            return _SkillEffectDetails(
                effects=_skill_effect_rows(skill.skill_effect),
                friend_effects=_skill_effect_rows(skill.friend_skill_effect),
                hide_effect_desc=_skill_hide_effect_text(skill),
            )
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        return _SkillEffectDetails([], [], None)


def _skill_effect_rows(effects: object) -> list[dict[str, Any]]:
    if not isinstance(effects, list):
        return []
    return [
        {"id": effect.effect_id, "info": text}
        for effect in effects
        if (text := _skill_effect_text(effect))
    ]


def _skill_hide_effect_text(skill: object) -> str | None:
    hide_effect = getattr(skill, "hide_effect", None)
    if hide_effect is None:
        return None
    description = str(getattr(hide_effect, "description", "") or "").strip()
    return format_plain_analyze_description(description or None)


def _skill_effect_text(effect: object) -> str:
    value = str(
        getattr(effect, "analyze_info", None) or getattr(effect, "info", "")
    ).strip()
    return format_analyze_description(value)


def _payload_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key, 0)
    if not isinstance(value, int | float | str):
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _skill_related_pets(value: object) -> str:
    if not isinstance(value, list):
        return ""
    names = [
        str(pet.get("name", "")).strip()
        for pet in value
        if isinstance(pet, dict) and str(pet.get("name", "")).strip()
    ]
    return f"关联精灵：{'、'.join(names)}" if names else ""
