# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Literal, NamedTuple, TypedDict

from seerapi_models import MintmarkORM, PetORM, SkillInPetORM, SoulmarkORM
from seerapi_models.mintmark import PetMintmarkLink, SkillMintmarkLink
from sqlalchemy.orm import object_session
from sqlmodel import col, select

from ironsbot.services.ai.analysis_parser import AnalyzeDescParser
from ironsbot.services.seer.images import (
    SeerImageSource,
    fetch_optional_image,
    to_data_uri,
)
from ironsbot.services.seer.item_exchange_price import load_item_exchange_prices
from ironsbot.services.seer.render_cache import RenderCache
from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    PET_INFO_IMAGES_PATH,
    SHARED_TEMPLATE_PATH,
)

from . import HtmlTemplateRenderer

SPECIAL_SOULMARK_PET_ID = 2500
HIDDEN_SKILL_ID = 19002
_ANALYZE_DESC_STYLES: dict[str, Callable[..., str]] = {
    "#f35555": lambda t: f'<b style="color:#60e0ff">{t}</b>',
}


class MintMarkDict(TypedDict):
    id: int
    name: str
    desc: str
    icon: str
    skills: list[str]


class ActivationItemPriceDict(TypedDict):
    source_name: str
    item_quantity: int
    currency_item_id: int
    currency_name: str
    amount: int
    purchase_limit: int | None
    currency_icon: str | None


class ActivationItemDict(TypedDict):
    id: int
    name: str
    icon: str | None
    prices: list[ActivationItemPriceDict]


class SkillDict(TypedDict):
    id: int
    name: str
    type_id: int
    type_name: str
    category_id: int
    category_name: str
    power: int
    max_pp: int
    accuracy: int | Literal["必中"]
    crit_rate: float | None
    priority: int
    must_hit: bool
    info: str | None
    learning_level: int | None
    is_special: bool
    is_advanced: bool
    is_fifth: bool
    effects: list[dict[str, Any]]
    activation_item: ActivationItemDict | None
    friend_bonus: bool
    hide_effect_desc: str | None


class GlossaryDict(NamedTuple):
    name: str
    desc: str


class SoulmarkDict(TypedDict):
    desc: str
    intensified: bool
    is_adv: bool
    pve_effective: bool | None
    tags: list[str]
    glossaries: set[GlossaryDict]
    icon_id: int | None
    icon: str | None


def _extract_skill(
    skill_in_pet: SkillInPetORM,
    activation_items: Mapping[int, ActivationItemDict],
) -> list[SkillDict]:
    skill = skill_in_pet.skill
    effects = [
        {
            "id": e.effect_id,
            "info": AnalyzeDescParser(e.analyze_info).to_html(_ANALYZE_DESC_STYLES),
        }
        for e in skill.skill_effect
    ]
    skill_activation_item = skill_in_pet.skill_activation_item
    activation_item = (
        activation_items.get(skill_activation_item.id)
        if skill_activation_item
        else None
    )
    hide_effect_desc = skill.hide_effect.description if skill.hide_effect else None
    result = SkillDict(
        id=skill.id,
        name=skill.name,
        type_id=skill.type.id,
        type_name=skill.type.name,
        category_id=skill.category.id,
        category_name=skill.category.name,
        power=skill.power,
        max_pp=skill.max_pp,
        accuracy="必中" if skill.must_hit else skill.accuracy,
        crit_rate=skill.crit_rate,
        priority=skill.priority,
        must_hit=skill.must_hit,
        info=skill.info,
        learning_level=skill_in_pet.learning_level,
        is_special=skill_in_pet.is_special,
        is_advanced=skill_in_pet.is_advanced,
        is_fifth=skill_in_pet.is_fifth,
        effects=effects,
        activation_item=activation_item,
        friend_bonus=False,
        hide_effect_desc=hide_effect_desc,
    )
    if len(skill.friend_skill_effect) > 0:
        friend_skill: SkillDict = {
            **result,
            "friend_bonus": True,
            "is_special": True,
            "effects": [
                {"id": e.effect_id, "info": e.info} for e in skill.friend_skill_effect
            ],
        }
        return [result, friend_skill]

    return [result]


def _build_activation_items(
    pet: PetORM,
    session: Any,
) -> dict[int, ActivationItemDict]:
    result: dict[int, ActivationItemDict] = {}
    for skill_link in pet.skill_links:
        item = skill_link.skill_activation_item
        if item is None:
            continue
        result.setdefault(
            item.id,
            ActivationItemDict(
                id=item.id,
                name=item.name,
                icon=None,
                prices=[],
            ),
        )

    prices_by_item = load_item_exchange_prices(session, result)
    for item_id, prices in prices_by_item.items():
        activation_item = result[item_id]
        activation_item["prices"] = [
            ActivationItemPriceDict(
                source_name=price.source_name,
                item_quantity=price.item_quantity,
                currency_item_id=price.currency_item_id,
                currency_name=price.currency_name,
                amount=price.amount,
                purchase_limit=price.purchase_limit,
                currency_icon=None,
            )
            for price in prices
        ]
    return result


async def _load_activation_item_icons(
    images: SeerImageSource,
    activation_items: Mapping[int, ActivationItemDict],
) -> None:
    item_ids = set(activation_items)
    item_ids.update(
        price["currency_item_id"]
        for item in activation_items.values()
        for price in item["prices"]
    )
    if not item_ids:
        return

    ordered_item_ids = sorted(item_ids)
    results = await asyncio.gather(
        *(
            fetch_optional_image(images, "item", str(item_id))
            for item_id in ordered_item_ids
        )
    )
    icons = {
        item_id: to_data_uri(result.data)
        for item_id, result in zip(ordered_item_ids, results, strict=True)
        if result.data is not None
    }
    for item in activation_items.values():
        item["icon"] = icons.get(item["id"])
        for price in item["prices"]:
            price["currency_icon"] = icons.get(price["currency_item_id"])


def _extract_soulmark(soulmarks: list[SoulmarkORM], pet: PetORM) -> list[SoulmarkDict]:
    results: list[SoulmarkDict] = []
    for sm in soulmarks:
        result = SoulmarkDict(
            desc=AnalyzeDescParser(sm.analyze_desc or sm.desc).to_html(
                _ANALYZE_DESC_STYLES
            ),
            intensified=sm.intensified,
            is_adv=sm.is_adv,
            pve_effective=sm.pve_effective,
            tags=[t.name for t in sm.tag] if sm.tag else [],
            glossaries=set(),
            icon_id=None,
            icon=None,
        )

        results.append(result)

    for i, sm in enumerate(reversed(results)):
        for glossary in pet.glossary_entry:
            if glossary.name not in sm["desc"] and i != 0:
                continue

            sm["glossaries"].add(GlossaryDict(name=glossary.name, desc=glossary.desc))

    return results


def _pet_introduction(pet: PetORM) -> str:
    encyclopedia = pet.encyclopedia
    if encyclopedia is None:
        return ""

    return encyclopedia.introduction.strip()


def _gender_icon_data_uri(gender_id: int) -> str:
    icon_path = PET_INFO_IMAGES_PATH / f"{gender_id}.png"
    if not icon_path.exists():
        icon_path = PET_INFO_IMAGES_PATH / "0.png"
    return to_data_uri(icon_path.read_bytes())


async def render_custom_pet_info(
    cache: RenderCache,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    pet: PetORM,
) -> bytes:
    """渲染精灵信息卡片图片，返回 PNG 图片字节"""
    cached = cache.get("custom_pet_info_v2", str(pet.id))
    if cached is not None:
        return cached

    base_stats = pet.base_stats.to_model().round()
    stats = base_stats.model_dump()
    advance_stats = None
    if pet.advance:
        advance_stats = pet.advance.base_stats.to_model().round().model_dump()

    session = object_session(pet)
    if session is None:
        raise RuntimeError
    activation_items = _build_activation_items(pet, session)
    soulmarks: list[SoulmarkDict] = _extract_soulmark(pet.soulmark, pet)
    if pet.id == SPECIAL_SOULMARK_PET_ID:
        soulmarks.append(
            {
                "desc": "登场首回合所有攻击先制+1同时增加20%暴击率",
                "intensified": True,
                "is_adv": False,
                "pve_effective": None,
                "tags": [],
                "glossaries": set(),
                "icon_id": None,
                "icon": None,
            }
        )
    all_skills: list[SkillDict] = [
        skill
        for skill_list in [
            _extract_skill(skill_link, activation_items)
            for skill_link in pet.skill_links
        ]
        for skill in skill_list
        if skill["id"] != HIDDEN_SKILL_ID
    ]
    special_skills: list[SkillDict] = []
    advanced_skills: list[SkillDict] = []
    fifth_skills: list[SkillDict] = []
    level_skills: list[SkillDict] = []
    for skill in all_skills:
        if skill["is_fifth"]:
            fifth_skills.append(skill)
        elif skill["is_advanced"]:
            advanced_skills.append(skill)
        elif skill["is_special"]:
            special_skills.append(skill)
        else:
            level_skills.append(skill)

    level_skills.sort(key=lambda s: s["learning_level"] or 0, reverse=True)
    skill_ids = [sl.skill_id for sl in pet.skill_links]
    stmt = (
        select(MintmarkORM)
        .outerjoin(
            SkillMintmarkLink,
            col(SkillMintmarkLink.mintmark_id) == col(MintmarkORM.id),
        )
        .outerjoin(
            PetMintmarkLink,
            col(PetMintmarkLink.mintmark_id) == col(MintmarkORM.id),
        )
        .where(
            col(SkillMintmarkLink.skill_id).in_(skill_ids)
            | (col(PetMintmarkLink.pet_id) == pet.id)
        )
        .where(
            col(PetMintmarkLink.pet_id).is_(None)
            | (col(PetMintmarkLink.pet_id) == pet.id)
        )
        .distinct()
    )
    mintmarks = session.execute(stmt).scalars().all()
    await _load_activation_item_icons(images, activation_items)
    pet_skill_names = {s["name"] for s in all_skills}
    type_ids = list({skill["type_id"] for skill in all_skills} | {pet.type.id})

    (
        pet_head_bytes,
        pet_body_bytes,
        *rest_results,
    ) = await asyncio.gather(
        images.fetch("pet_head", str(pet.resource_id)),
        images.fetch("pet_body", str(pet.resource_id)),
        *(images.fetch("element_type", str(tid)) for tid in type_ids),
        images.fetch("element_type", "prop"),
        *(images.fetch("mintmark", str(mm.id)) for mm in mintmarks),
    )

    type_icon_count = len(type_ids) + 1  # +1 for "prop"
    type_icon_results = rest_results[:type_icon_count]
    mm_icon_results = rest_results[type_icon_count:]

    type_icons: dict[int | str, str] = {
        tid: to_data_uri(data)
        for tid, data in zip(type_ids, type_icon_results[:-1], strict=True)
    }
    type_icons["prop"] = to_data_uri(type_icon_results[-1])

    skill_marks: list[MintMarkDict] = [
        MintMarkDict(
            id=mm.id,
            name=mm.name,
            desc=mm.desc,
            icon=to_data_uri(icon_bytes),
            skills=list(
                dict.fromkeys(s.name for s in mm.skill if s.name in pet_skill_names)
            ),
        )
        for mm, icon_bytes in zip(mintmarks, mm_icon_results, strict=True)
    ]

    result = await render_html(
        template_path=[CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        template_name="template.html.j2",
        templates={
            "pet_name": pet.name,
            "pet_id": pet.id,
            "pet_gender_id": pet.gender.id,
            "pet_gender_icon": _gender_icon_data_uri(pet.gender.id),
            "pet_type_id": pet.type.id,
            "pet_type_name": pet.type.name,
            "pet_head_img": to_data_uri(pet_head_bytes),
            "pet_body_img": to_data_uri(pet_body_bytes),
            "type_icons": type_icons,
            "pet_introduction": _pet_introduction(pet),
            "stats": stats,
            "advance_stats": advance_stats,
            "soulmarks": soulmarks,
            "skill_marks": skill_marks,
            "fifth_skills": fifth_skills[::-1],
            "advanced_skills": advanced_skills[::-1],
            "special_skills": special_skills[::-1],
            "level_skills": level_skills,
        },
        max_width=1200,
        allow_refit=False,
    )
    cache.put("custom_pet_info_v2", str(pet.id), result)
    return result
