# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation for detached pet information render snapshots."""

from __future__ import annotations

import base64
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from .analyze_description import (
    format_analyze_description,
    format_plain_analyze_description,
)
from .custom_pet_models import (
    ActivationItemDict,
    ActivationItemPriceDict,
    MintMarkDict,
    PartnerItemDict,
    PartnerSkillDict,
    PetPartnerDict,
    SkillDict,
    SoulmarkDict,
    SpecialEffectDict,
)
from .pet_effect_presentation import assign_special_effect_colors
from .pet_info_models import (
    PetInfoAssets,
    PetInfoRenderDocument,
    PetInfoSnapshot,
    PetItemSnapshot,
    PetPartnerSnapshot,
    PetSkillEffectSnapshot,
    PetSkillSnapshot,
    PetSoulmarkDisplayAddition,
    PetSoulmarkSnapshot,
)

_HIDDEN_SKILL_ID = 19002
_RICH_TEXT_COLOR_OPEN_RE = re.compile(r"<color=(#[0-9a-fA-F]{6})>")
_RICH_TEXT_TAG_RE = re.compile(r"</?[^>]+>")


def present_pet_info(
    snapshot: PetInfoSnapshot,
    assets: PetInfoAssets,
) -> PetInfoRenderDocument:
    """Create a template-ready document without ORM, I/O, or current time."""
    item_icons = assets.item_icon_by_id
    effect_icons = assets.special_effect_icon_by_status_id
    activation_items = {
        item.id: _item_view(item, item_icons) for item in snapshot.activation_items
    }
    special_effects = _special_effect_views(snapshot, effect_icons)
    effect_colors = {
        effect["name"]: color
        for effect in special_effects
        if (color := effect.get("color")) is not None
    }
    soulmarks = _soulmark_views(snapshot, effect_colors)
    soulmarks.extend(
        _soulmark_display_addition_views(
            snapshot.display.soulmark_display_additions,
            effect_colors,
        )
    )
    partner = _partner_view(snapshot.partner, item_icons)
    base_soulmarks, upgraded_soulmarks = _partition_soulmarks(
        soulmarks,
        snapshot.partner_upgraded_soulmark_ids,
    )
    all_skills = [
        item
        for skill in snapshot.skills
        for item in _skill_views(skill, activation_items, effect_colors)
        if item["id"] != _HIDDEN_SKILL_ID
    ]
    special_skills, advanced_skills, fifth_skills, level_skills = _group_skills(
        all_skills
    )
    type_ids = tuple(
        sorted({skill["type_id"] for skill in all_skills} | {snapshot.pet.type_id})
    )
    type_assets = assets.type_icon_by_id
    templates: dict[str, object] = {
        "pet_name": snapshot.pet.name,
        "pet_id": snapshot.pet.id,
        "pet_gender_id": snapshot.pet.gender_id,
        "pet_gender_icon": _data_uri(assets.gender_icon),
        "pet_type_id": snapshot.pet.type_id,
        "pet_type_name": snapshot.pet.type_name,
        "pet_head_img": _data_uri(assets.pet_head),
        "pet_body_img": _data_uri(assets.pet_body),
        "type_icons": {
            **{type_id: _data_uri(type_assets[type_id]) for type_id in type_ids},
            "prop": _data_uri(type_assets["prop"]),
        },
        "pet_introduction": snapshot.pet.introduction,
        "stats": _stats_view(snapshot.base_stats),
        "advance_stats": (
            _stats_view(snapshot.advance_stats)
            if snapshot.advance_stats is not None
            else None
        ),
        "soulmarks": tuple(soulmarks),
        "base_soulmarks": tuple(base_soulmarks),
        "upgraded_soulmarks": tuple(upgraded_soulmarks),
        "pet_partner": partner,
        "special_effects": tuple(special_effects),
        "skill_marks": tuple(_skill_mintmark_views(snapshot, assets)),
        "fifth_skills": tuple(reversed(fifth_skills)),
        "advanced_skills": tuple(reversed(advanced_skills)),
        "special_skills": tuple(reversed(special_skills)),
        "level_skills": tuple(level_skills),
    }
    return PetInfoRenderDocument(
        template_name="template.html.j2",
        templates=MappingProxyType(templates),
    )


def _data_uri(data: bytes, content_type: str = "image/png") -> str:
    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


def _stats_view(stats: Any) -> dict[str, int]:
    return {
        "atk": stats.atk,
        "def_": stats.def_,
        "sp_atk": stats.sp_atk,
        "sp_def": stats.sp_def,
        "spd": stats.spd,
        "hp": stats.hp,
        "total": stats.total,
    }


def _item_view(
    item: PetItemSnapshot,
    icons: Mapping[int, bytes],
) -> ActivationItemDict:
    return ActivationItemDict(
        id=item.id,
        name=item.name,
        icon=_asset_data_uri(icons.get(item.id)),
        prices=[
            ActivationItemPriceDict(
                source_name=price.source_name,
                item_quantity=price.item_quantity,
                currency_item_id=price.currency_item_id,
                currency_name=price.currency_name,
                amount=price.amount,
                purchase_limit=price.purchase_limit,
                currency_icon=_asset_data_uri(icons.get(price.currency_item_id)),
            )
            for price in item.prices
        ],
    )


def _asset_data_uri(asset: bytes | None) -> str | None:
    return _data_uri(asset) if asset is not None else None


def _special_effect_views(
    snapshot: PetInfoSnapshot,
    icons: Mapping[int, bytes],
) -> list[SpecialEffectDict]:
    effects = [
        SpecialEffectDict(
            name=effect.name,
            desc=effect.description,
            sources=list(effect.sources),
            glossary_id=effect.glossary_id,
            status_id=effect.status_id,
            icon=(
                _asset_data_uri(icons.get(effect.status_id))
                if effect.status_id is not None
                else None
            ),
        )
        for effect in snapshot.display.special_effects
    ]
    assign_special_effect_colors(effects, snapshot.rich_texts)
    return effects


def _soulmark_views(
    snapshot: PetInfoSnapshot,
    effect_colors: Mapping[str, str],
) -> list[SoulmarkDict]:
    order = snapshot.display.soulmark_order_by_id
    icons = snapshot.display.soulmark_icon_by_id
    result: list[SoulmarkDict] = []
    for soulmark in sorted(
        snapshot.soulmarks,
        key=lambda value: (
            value.id not in order,
            order.get(value.id, value.id),
            value.id,
        ),
    ):
        icon = icons.get(soulmark.id)
        result.append(
            SoulmarkDict(
                id=soulmark.id,
                desc=_format_soulmark_description(soulmark, effect_colors),
                intensified=soulmark.intensified,
                intensified_to_id=soulmark.intensified_to_id,
                is_adv=soulmark.is_adv,
                pve_effective=soulmark.pve_effective,
                tags=list(soulmark.tags),
                icon_id=icon.icon_id if icon is not None else None,
                icon_asset_url=None,
                icon=(
                    _data_uri(icon.png, icon.content_type)
                    if icon is not None
                    else None
                ),
            )
        )
    return result


def _format_soulmark_description(
    soulmark: PetSoulmarkSnapshot | PetSoulmarkDisplayAddition,
    effect_colors: Mapping[str, str],
) -> str:
    if soulmark.analyze_desc:
        return format_analyze_description(soulmark.analyze_desc, effect_colors)
    if soulmark.formatting_adjustment:
        value = soulmark.formatting_adjustment.replace("\r\n", "|").replace("\n", "|")
        value = _RICH_TEXT_COLOR_OPEN_RE.sub(r"[color=\1]", value)
        value = _RICH_TEXT_TAG_RE.sub("", value.replace("</color>", "[/color]"))
        return format_analyze_description(value, effect_colors)
    return format_analyze_description(soulmark.desc, effect_colors)


def _soulmark_display_addition_views(
    additions: Sequence[PetSoulmarkDisplayAddition],
    effect_colors: Mapping[str, str],
) -> list[SoulmarkDict]:
    """Append build-time display corrections after raw soulmarks.

    Their source schema mirrors the raw presentation fields, allowing a future
    data correction to use rich text and tags without a pet-specific branch.
    """
    return [
        SoulmarkDict(
            id=addition.id,
            desc=_format_soulmark_description(addition, effect_colors),
            intensified=addition.intensified,
            intensified_to_id=addition.intensified_to_id,
            is_adv=addition.is_adv,
            pve_effective=addition.pve_effective,
            tags=list(addition.tags),
            icon_id=None,
            icon_asset_url=None,
            icon=None,
        )
        for addition in additions
    ]


def _partner_view(
    partner: PetPartnerSnapshot | None,
    icons: Mapping[int, bytes],
) -> PetPartnerDict | None:
    if partner is None:
        return None
    skill: PartnerSkillDict | None = None
    if partner.skill is not None:
        skill = PartnerSkillDict(
            id=partner.skill.id,
            name=partner.skill.name,
            activation_item=(
                _partner_item_view(partner.skill.activation_item, icons)
                if partner.skill.activation_item is not None
                else None
            ),
        )
    return PetPartnerDict(
        name=partner.name,
        cost_item=_partner_item_view(partner.cost_item, icons),
        skill=skill,
    )


def _partner_item_view(
    item: PetItemSnapshot,
    icons: Mapping[int, bytes],
) -> PartnerItemDict:
    result = _item_view(item, icons)
    return PartnerItemDict(
        id=result["id"],
        name=result["name"],
        quantity=item.quantity,
        icon=result["icon"],
        prices=result["prices"],
    )


def _partition_soulmarks(
    soulmarks: Sequence[SoulmarkDict],
    partner_upgraded_soulmark_ids: frozenset[int],
) -> tuple[list[SoulmarkDict], list[SoulmarkDict]]:
    upgraded = {
        index for index, soulmark in enumerate(soulmarks) if soulmark["intensified"]
    }
    upgraded.update(
        index
        for index, soulmark in enumerate(soulmarks)
        if soulmark["id"] in partner_upgraded_soulmark_ids
    )
    return (
        [value for index, value in enumerate(soulmarks) if index not in upgraded],
        [value for index, value in enumerate(soulmarks) if index in upgraded],
    )


def _skill_views(
    skill: PetSkillSnapshot,
    activation_items: Mapping[int, ActivationItemDict],
    effect_colors: Mapping[str, str],
) -> list[SkillDict]:
    result = SkillDict(
        id=skill.id,
        name=skill.name,
        type_id=skill.type_id,
        type_name=skill.type_name,
        category_id=skill.category_id,
        category_name=skill.category_name,
        power=skill.power,
        max_pp=skill.max_pp,
        accuracy="必中" if skill.must_hit else skill.accuracy,
        crit_rate=skill.crit_rate,
        priority=skill.priority,
        must_hit=skill.must_hit,
        info=format_plain_analyze_description(skill.info, effect_colors),
        learning_level=skill.learning_level,
        is_special=skill.is_special,
        is_advanced=skill.is_advanced,
        is_fifth=skill.is_fifth,
        effects=_effect_views(skill.effects, effect_colors),
        activation_item=activation_items.get(skill.activation_item_id or 0),
        friend_bonus=False,
        hide_effect_desc=format_plain_analyze_description(
            skill.hide_effect_description,
            effect_colors,
        ),
    )
    if not skill.friend_effects:
        return [result]
    return [
        result,
        cast(
            "SkillDict",
            {
                **result,
                "friend_bonus": True,
                "is_special": True,
                "effects": _effect_views(skill.friend_effects, effect_colors),
            },
        ),
    ]


def _effect_views(
    effects: Sequence[PetSkillEffectSnapshot],
    colors: Mapping[str, str],
) -> list[dict[str, Any]]:
    return [
        {
            "id": effect.effect_id,
            "info": format_analyze_description(
                effect.analyze_info or effect.info,
                colors,
            ),
        }
        for effect in effects
    ]


def _group_skills(
    skills: Sequence[SkillDict],
) -> tuple[list[SkillDict], list[SkillDict], list[SkillDict], list[SkillDict]]:
    special: list[SkillDict] = []
    advanced: list[SkillDict] = []
    fifth: list[SkillDict] = []
    level: list[SkillDict] = []
    for skill in skills:
        if skill["is_fifth"]:
            fifth.append(skill)
        elif skill["is_advanced"]:
            advanced.append(skill)
        elif skill["is_special"]:
            special.append(skill)
        else:
            level.append(skill)
    level.sort(key=lambda skill: skill["learning_level"] or 0, reverse=True)
    return special, advanced, fifth, level


def _skill_mintmark_views(
    snapshot: PetInfoSnapshot,
    assets: PetInfoAssets,
) -> list[MintMarkDict]:
    icons = assets.mintmark_icon_by_id
    return [
        MintMarkDict(
            id=mintmark.id,
            name=mintmark.name,
            desc=mintmark.description,
            icon=_data_uri(icons[mintmark.id]),
            skills=list(mintmark.skill_names),
        )
        for mintmark in snapshot.skill_mintmarks
    ]
