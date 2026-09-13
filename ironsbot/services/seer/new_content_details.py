# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-neutral detail selection and text for the weekly content index."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.core.value_coercion import require_bool_flag

from .autocard import AutocardEntry, AutocardPromptValue
from .new_content import NewContentSnapshotChangedError
from .pet_query import PetImageSelection
from .query_result import QueryReply

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from .autocard import AutocardService
    from .equipment import EquipmentQueryService
    from .mintmark import MintmarkQueryService
    from .new_content import NewContentItem, NewContentSnapshot
    from .pet_query import PetQueryService


NewContentDetail = str | QueryReply | AutocardEntry | None


@dataclass(frozen=True, slots=True)
class NewContentDetailService:
    """Reuse domain selectors; platform adapters only deliver the returned detail."""

    pet: PetQueryService
    mintmark: MintmarkQueryService
    equipment: EquipmentQueryService
    autocard: AutocardService
    selection_scope: Callable[[NewContentSnapshot], AbstractContextManager[None]]

    async def select(
        self, snapshot: NewContentSnapshot, item: NewContentItem
    ) -> NewContentDetail:
        if item not in snapshot.items:
            raise NewContentSnapshotChangedError
        with self.selection_scope(snapshot):
            return await self._select(item)

    async def _select(self, item: NewContentItem) -> NewContentDetail:
        if item.category == "autocard_sanctuary_effect":
            return format_new_content_autocard_sanctuary_effect_detail(item)
        if item.category == "achievement":
            return format_new_content_achievement_detail(item)
        if item.category == "skill":
            return format_new_content_skill_detail(item)
        if item.category in {"autocard_card", "autocard_role"}:
            return self.autocard.select(
                AutocardPromptValue(
                    kind="role" if item.category == "autocard_role" else "card",
                    item_id=item.entity_id,
                )
            )
        if item.category in {"pet", "peak_pool", "peak_expert_pool"}:
            result = await self.pet.select_info(item.entity_id)
        elif item.category == "pet_skin":
            result = await self.pet.select_image(
                PetImageSelection(
                    resource_id=int(item.payload.get("resource_id", item.entity_id)),
                    name=item.name,
                    skin_id=item.entity_id,
                )
            )
        elif item.category == "mintmark":
            result = await self.mintmark.select_mintmark(item.entity_id)
        else:
            result = await self.equipment.select(
                "suit" if item.category == "suit" else "equip", item.entity_id
            )
        return result.message or result.reply


def format_new_content_achievement_detail(item: NewContentItem) -> str:
    lines = [
        f"🏆【{item.name}】",
        f"🆔：{item.entity_id}",
        f"成就点数：{int(item.payload.get('point', 0))}点",
    ]
    description = str(item.payload.get("description", "")).strip()
    if description:
        lines.append(f"说明：{description}")
    titles = item.payload.get("titles", [])
    if isinstance(titles, list) and titles:
        names = "、".join(str(title.get("name", "")) for title in titles)
        lines.append(f"关联称号：{names}")
    return "\n".join(lines)


def format_new_content_skill_detail(item: NewContentItem) -> str:
    payload = item.payload
    change = "修改" if item.change_kind == "modified" else "新增"
    lines = [
        f"⚔️【{item.name}】",
        f"状态：{change}",
        f"🆔：{item.entity_id}",
    ]
    lines.extend(_skill_stat_lines(payload))
    if description := str(payload.get("info", "")).strip():
        lines.append(f"效果：{description}")
    if related := _skill_related_pets(payload.get("pets")):
        lines.append(f"关联精灵：{related}")
    return "\n".join(lines)


def format_new_content_autocard_sanctuary_effect_detail(
    item: NewContentItem,
) -> str:
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
    if require_bool_flag(payload.get("must_hit", False), field="skill.must_hit"):
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
        suffix = f"（{pet_id}）" if pet_id else ""
        related.append(f"{name}{suffix}{_skill_pet_label(pet)}")
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
