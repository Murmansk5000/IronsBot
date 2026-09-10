# SPDX-License-Identifier: GPL-3.0-or-later
"""Text detail builders for weekly new-content selections."""

from __future__ import annotations

from typing import Any

from ironsbot.services.seer.new_content import (
    NewContentItem,
    format_new_content_change_summary,
)


def achievement_detail(item: NewContentItem) -> str:
    lines = [
        f"🏆【{item.name}】",
        f"🆔：{item.entity_id}",
        f"成就点数：{int(item.payload.get('point', 0))}点",
    ]
    if summary := format_new_content_change_summary(item):
        lines.append(f"本次修改：{summary}")
    description = str(item.payload.get("description", "")).strip()
    if description:
        lines.append(f"说明：{description}")
    titles = item.payload.get("titles", [])
    if isinstance(titles, list) and titles:
        names = "、".join(str(title.get("name", "")) for title in titles)
        lines.append(f"关联称号：{names}")
    return "\n".join(lines)


def skill_detail(item: NewContentItem) -> str:
    payload = item.payload
    change = "修改" if item.change_kind == "modified" else "新增"
    lines = [
        f"⚔️【{item.name}】",
        f"状态：{change}",
        f"🆔：{item.entity_id}",
    ]
    if summary := format_new_content_change_summary(item):
        lines.append(f"本次修改：{summary}")
    lines.extend(_skill_stat_lines(payload))
    if description := str(payload.get("info", "")).strip():
        lines.append(f"效果：{description}")
    if related := _skill_related_pets(payload.get("pets")):
        lines.append(f"关联精灵：{related}")
    return "\n".join(lines)


def sanctuary_effect_detail(item: NewContentItem) -> str:
    payload = item.payload
    sanctuary_name = str(payload.get("sanctuary_name", "")).strip()
    sanctuary_id = int(payload.get("sanctuary_id", 0))
    sanctuary = sanctuary_name or f"圣域 {sanctuary_id}"
    unlock_round = int(payload.get("unlock_round", 0))
    change = "修改" if item.change_kind == "modified" else "新增"
    phase = "基础圣域" if unlock_round == 0 else f"第 {unlock_round} 回合祝印"
    lines = [
        f"🃏【{item.name}】",
        f"状态：{change}",
        f"圣域：{sanctuary}",
        f"阶段：{phase}",
    ]
    if summary := format_new_content_change_summary(item):
        lines.append(f"本次修改：{summary}")
    pet_name = str(payload.get("sanctuary_pet_name", "")).strip()
    pet_id = int(payload.get("sanctuary_pet_id", 0))
    if pet_name or pet_id:
        pet = pet_name or "未命名精灵王"
        suffix = f"（{pet_id}）" if pet_id else ""
        lines.append(f"关联精灵王：{pet}{suffix}")
    buff_id = str(payload.get("buff_id", "")).strip()
    buff_param = str(payload.get("buff_param", "")).strip()
    if buff_id:
        buff = buff_id if not buff_param else f"{buff_id}（参数：{buff_param}）"
        lines.append(f"关联 Buff：{buff}")
    description = str(payload.get("description", "")).strip()
    if description:
        lines.append(f"效果：{description}")
    return "\n".join(lines)


def _skill_stat_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    power = int(payload.get("power", 0))
    max_pp = int(payload.get("max_pp", 0))
    if power or max_pp:
        lines.append(f"威力：{power}｜PP：{max_pp}")
    if bool(payload.get("must_hit", False)):
        lines.append("命中：必中")
    elif (accuracy := int(payload.get("accuracy", 0))) > 0:
        lines.append(f"命中：{accuracy}%")
    if (crit_rate := int(payload.get("crit_rate", 0))) > 0:
        lines.append(f"暴击率：{crit_rate}%")
    if (priority := int(payload.get("priority", 0))) != 0:
        lines.append(f"先制：{priority:+d}")
    if (atk_num := int(payload.get("atk_num", 0))) > 1:
        lines.append(f"攻击次数：{atk_num}")
    return lines


def _skill_related_pets(value: object) -> str:
    if not isinstance(value, list):
        return ""
    related: list[str] = []
    for pet in value:
        if not isinstance(pet, dict):
            continue
        name = str(pet.get("name", "")).strip() or "未命名精灵"
        pet_id = int(pet.get("id", 0))
        label = _skill_pet_label(pet)
        suffix = f"（{pet_id}）" if pet_id else ""
        related.append(f"{name}{suffix}{label}")
    return "、".join(related)


def _skill_pet_label(pet: dict[str, Any]) -> str:
    if bool(pet.get("is_fifth", False)):
        return "（第五技能）"
    if bool(pet.get("is_advanced", False)):
        return "（强化技能）"
    if bool(pet.get("is_special", False)):
        return "（特殊技能）"
    if (level := int(pet.get("learning_level", 0))) > 0:
        return f"（Lv.{level}）"
    return ""
