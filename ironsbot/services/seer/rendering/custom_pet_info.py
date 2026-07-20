# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal, TypedDict

from seerapi_models import MintmarkORM, PetORM, SkillInPetORM, SoulmarkORM
from seerapi_models.mintmark import PetMintmarkLink, SkillMintmarkLink
from sqlalchemy.orm import object_session
from sqlmodel import col, select

from ironsbot.services.ai.analysis_parser import AnalyzeDescParser
from ironsbot.services.seer.effect_description import load_effect_descriptions
from ironsbot.services.seer.images import (
    SeerImageSource,
    fetch_optional_image,
    to_data_uri,
)
from ironsbot.services.seer.item_exchange_price import load_item_exchange_prices
from ironsbot.services.seer.pet_partner import PetPartner, load_pet_partner
from ironsbot.services.seer.render_cache import RenderCache
from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    PET_INFO_IMAGES_PATH,
    SHARED_TEMPLATE_PATH,
)

from . import HtmlTemplateRenderer

SPECIAL_SOULMARK_PET_ID = 2500
HIDDEN_SKILL_ID = 19002
PARTNER_UPGRADE_MIN_SIMILARITY = 0.8
PARTNER_UPGRADE_MIN_DELTA = 0.01
_ANALYZE_DESC_STYLES: dict[str, Callable[..., str]] = {
    "#f35555": lambda t: f'<b style="color:#60e0ff">{t}</b>',
}
_SPECIAL_EFFECT_COLOR = "#f35555"


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


class SoulmarkDict(TypedDict):
    id: int
    desc: str
    intensified: bool
    intensified_to_id: int | None
    is_adv: bool
    pve_effective: bool | None
    tags: list[str]
    icon_id: int | None
    icon: str | None


class SpecialEffectDict(TypedDict):
    name: str
    desc: str | None
    sources: list[str]


class PartnerItemDict(TypedDict):
    id: int
    name: str
    quantity: int
    icon: str | None
    prices: list[ActivationItemPriceDict]


class PartnerSkillDict(TypedDict):
    id: int
    name: str
    activation_item: PartnerItemDict | None


class PetPartnerDict(TypedDict):
    name: str
    cost_item: PartnerItemDict
    skill: PartnerSkillDict | None


@dataclass(frozen=True, slots=True)
class _SkillMintmarkSnapshot:
    id: int
    name: str
    desc: str
    skills: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PetRenderSnapshot:
    id: int
    name: str
    resource_id: int
    gender_id: int
    type_id: int
    type_name: str
    introduction: str


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
    activation_item_id = int(skill_in_pet.skill_activation_item_id or 0)
    activation_item = activation_items.get(activation_item_id)
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
    activation_item_ids: set[int] = set()
    for skill_link in pet.skill_links:
        item_id = int(skill_link.skill_activation_item_id or 0)
        if item_id <= 0:
            continue
        activation_item_ids.add(item_id)
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

    prices_by_item = load_item_exchange_prices(session, activation_item_ids)
    for item_id, prices in prices_by_item.items():
        activation_item = result.get(item_id)
        if activation_item is None:
            item_name = next(
                (price.item_name for price in prices if price.item_name),
                "",
            )
            if not item_name:
                continue
            activation_item = ActivationItemDict(
                id=item_id,
                name=item_name,
                icon=None,
                prices=[],
            )
            result[item_id] = activation_item
        activation_item["prices"] = _to_activation_item_prices(
            item_id,
            prices_by_item,
        )
    return result


def _to_activation_item_prices(
    item_id: int,
    prices_by_item: Mapping[int, list[Any]],
) -> list[ActivationItemPriceDict]:
    return [
        ActivationItemPriceDict(
            source_name=price.source_name,
            item_quantity=price.item_quantity,
            currency_item_id=price.currency_item_id,
            currency_name=price.currency_name,
            amount=price.amount,
            purchase_limit=price.purchase_limit,
            currency_icon=None,
        )
        for price in prices_by_item.get(item_id, [])
    ]


def _build_pet_partner(
    partner: PetPartner | None,
    session: Any,
) -> PetPartnerDict | None:
    if partner is None:
        return None

    requirements = [
        (
            partner.cost_item_id,
            partner.cost_item_name,
            partner.cost_item_quantity,
        )
    ]
    if partner.skill and partner.skill.activation_item:
        item = partner.skill.activation_item
        requirements.append((item.item_id, item.name, item.quantity))
    prices_by_item = load_item_exchange_prices(
        session,
        (item_id for item_id, _name, _quantity in requirements),
    )

    def requirement(
        item_id: int,
        name: str,
        quantity: int,
    ) -> PartnerItemDict:
        return PartnerItemDict(
            id=item_id,
            name=name or f"道具{item_id}",
            quantity=max(1, quantity),
            icon=None,
            prices=_to_activation_item_prices(item_id, prices_by_item),
        )

    skill: PartnerSkillDict | None = None
    if partner.skill:
        activation_item = partner.skill.activation_item
        skill = PartnerSkillDict(
            id=partner.skill.skill_id,
            name=partner.skill.name,
            activation_item=(
                requirement(
                    activation_item.item_id,
                    activation_item.name,
                    activation_item.quantity,
                )
                if activation_item
                else None
            ),
        )
    return PetPartnerDict(
        name=partner.name,
        cost_item=requirement(
            partner.cost_item_id,
            partner.cost_item_name,
            partner.cost_item_quantity,
        ),
        skill=skill,
    )


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


async def _load_pet_partner_item_icons(
    images: SeerImageSource,
    partner: PetPartnerDict | None,
) -> None:
    if partner is None:
        return

    items = [partner["cost_item"]]
    skill = partner["skill"]
    if skill and skill["activation_item"]:
        items.append(skill["activation_item"])
    item_ids = {item["id"] for item in items}
    item_ids.update(
        price["currency_item_id"] for item in items for price in item["prices"]
    )
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
    for item in items:
        item["icon"] = icons.get(item["id"])
        for price in item["prices"]:
            price["currency_icon"] = icons.get(price["currency_item_id"])


def _extract_soulmark(soulmarks: list[SoulmarkORM]) -> list[SoulmarkDict]:
    results: list[SoulmarkDict] = []
    for sm in soulmarks:
        result = SoulmarkDict(
            id=int(sm.id),
            desc=AnalyzeDescParser(sm.analyze_desc or sm.desc).to_html(
                _ANALYZE_DESC_STYLES
            ),
            intensified=sm.intensified,
            intensified_to_id=sm.intensified_to_id,
            is_adv=sm.is_adv,
            pve_effective=sm.pve_effective,
            tags=[t.name for t in sm.tag] if sm.tag else [],
            icon_id=None,
            icon=None,
        )

        results.append(result)

    return results


def _partition_soulmarks(
    soulmarks: list[SoulmarkDict],
    partner: PetPartner | None,
) -> tuple[list[SoulmarkDict], list[SoulmarkDict]]:
    upgraded_indexes = {
        index for index, soulmark in enumerate(soulmarks) if soulmark["intensified"]
    }
    if partner is not None:
        partner_upgrade_index = _find_partner_upgrade_soulmark_index(
            soulmarks,
            partner,
        )
        if partner_upgrade_index is not None:
            upgraded_indexes.add(partner_upgrade_index)

    return (
        [
            soulmark
            for index, soulmark in enumerate(soulmarks)
            if index not in upgraded_indexes
        ],
        [
            soulmark
            for index, soulmark in enumerate(soulmarks)
            if index in upgraded_indexes
        ],
    )


def _find_partner_upgrade_soulmark_index(
    soulmarks: Sequence[SoulmarkDict],
    partner: PetPartner,
) -> int | None:
    """Locate the real upgraded soulmark instead of rendering partner text again."""
    indexes_by_id = {soulmark["id"]: index for index, soulmark in enumerate(soulmarks)}
    for soulmark in soulmarks:
        upgraded_id = soulmark["intensified_to_id"]
        if upgraded_id is not None and upgraded_id in indexes_by_id:
            return indexes_by_id[upgraded_id]

    after = _normalize_soulmark_text(partner.after_description)
    before = _normalize_soulmark_text(partner.before_description)
    if not after:
        return None

    candidates = [
        (
            SequenceMatcher(
                None, _normalize_soulmark_text(soulmark["desc"]), after
            ).ratio(),
            SequenceMatcher(
                None,
                _normalize_soulmark_text(soulmark["desc"]),
                before,
            ).ratio(),
            index,
        )
        for index, soulmark in enumerate(soulmarks)
    ]
    if not candidates:
        return None
    after_score, before_score, index = max(
        candidates,
        key=lambda candidate: (candidate[0] - candidate[1], candidate[0]),
    )
    return (
        index
        if after_score >= PARTNER_UPGRADE_MIN_SIMILARITY
        and after_score > before_score + PARTNER_UPGRADE_MIN_DELTA
        else None
    )


def _normalize_soulmark_text(value: str | None) -> str:
    without_markup = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"[\W_]+", "", without_markup).casefold()


def _red_effect_names(
    description: str | None,
    known_names: Mapping[str, str],
) -> list[str]:
    if not description:
        return []

    names: list[str] = []
    for colored_text in AnalyzeDescParser(description).colored_texts(
        _SPECIAL_EFFECT_COLOR
    ):
        text = colored_text.strip()
        if not text:
            continue

        # The parser intentionally merges adjacent segments with the same
        # color. Split a merged red span back into its known glossary terms
        # before falling back to the raw text.
        candidates = sorted(
            ((text.find(name), name) for name in known_names if name and name in text),
            key=lambda item: (item[0], -len(item[1])),
        )
        matched_ranges: list[tuple[int, int]] = []
        matched_names: list[str] = []
        for start, name in candidates:
            end = start + len(name)
            if any(
                start < other_end and other_start < end
                for other_start, other_end in matched_ranges
            ):
                continue
            matched_ranges.append((start, end))
            matched_names.append(name)
        names.extend(matched_names or [text])

    return list(dict.fromkeys(names))


def _extract_special_effects(
    pet: PetORM,
    official_descriptions: Mapping[str, str] | None = None,
) -> list[SpecialEffectDict]:
    """Collect red-highlighted named effects from soulmarks and skills."""
    known_descriptions = dict(official_descriptions or {})
    glossary_descriptions = {
        glossary.name: glossary.desc
        for glossary in pet.glossary_entry
        if glossary.name and glossary.desc
    }
    # Pet-linked glossary entries are more specific than a global EffectDes row.
    known_descriptions.update(glossary_descriptions)
    effects_by_name: dict[str, SpecialEffectDict] = {}

    def add(description: str | None, source: str) -> None:
        for name in _red_effect_names(description, known_descriptions):
            effect = effects_by_name.setdefault(
                name,
                SpecialEffectDict(
                    name=name,
                    desc=known_descriptions.get(name),
                    sources=[],
                ),
            )
            if source not in effect["sources"]:
                effect["sources"].append(source)

    for soulmark in pet.soulmark:
        add(soulmark.analyze_desc or soulmark.desc, "魂印")

    for skill_link in pet.skill_links:
        skill = skill_link.skill
        if skill.id == HIDDEN_SKILL_ID:
            continue
        source = f"技能·{skill.name}"
        add(skill.info, source)
        for effect in (*skill.skill_effect, *skill.friend_skill_effect):
            add(getattr(effect, "analyze_info", None) or effect.info, source)
        if skill.hide_effect:
            add(skill.hide_effect.description, source)

    return list(effects_by_name.values())


def _pet_introduction(pet: PetORM) -> str:
    encyclopedia = pet.encyclopedia
    if encyclopedia is None:
        return ""

    return encyclopedia.introduction.strip()


def _snapshot_skill_mintmarks(
    mintmarks: Sequence[MintmarkORM],
    pet_skill_names: set[str],
) -> tuple[_SkillMintmarkSnapshot, ...]:
    return tuple(
        _SkillMintmarkSnapshot(
            id=int(mintmark.id),
            name=str(mintmark.name),
            desc=str(mintmark.desc or ""),
            skills=tuple(
                dict.fromkeys(
                    str(skill.name)
                    for skill in mintmark.skill
                    if skill.name in pet_skill_names
                )
            ),
        )
        for mintmark in mintmarks
    )


def _snapshot_pet_render_data(pet: PetORM) -> _PetRenderSnapshot:
    return _PetRenderSnapshot(
        id=int(pet.id),
        name=str(pet.name),
        resource_id=int(pet.resource_id),
        gender_id=int(pet.gender.id),
        type_id=int(pet.type.id),
        type_name=str(pet.type.name),
        introduction=_pet_introduction(pet),
    )


def _group_skills(
    all_skills: list[SkillDict],
) -> tuple[
    list[SkillDict],
    list[SkillDict],
    list[SkillDict],
    list[SkillDict],
]:
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
    level_skills.sort(key=lambda skill: skill["learning_level"] or 0, reverse=True)
    return special_skills, advanced_skills, fifth_skills, level_skills


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
    pet_id = int(pet.id)
    cached = cache.get("custom_pet_info_v5", str(pet_id))
    if cached is not None:
        return cached

    pet_data = _snapshot_pet_render_data(pet)
    base_stats = pet.base_stats.to_model().round()
    stats = base_stats.model_dump()
    advance_stats = None
    if pet.advance:
        advance_stats = pet.advance.base_stats.to_model().round().model_dump()

    session = object_session(pet)
    if session is None:
        raise RuntimeError
    activation_items = _build_activation_items(pet, session)
    soulmarks: list[SoulmarkDict] = _extract_soulmark(pet.soulmark)
    partner_data = load_pet_partner(session, pet_id)
    pet_partner = _build_pet_partner(partner_data, session)
    special_effects = _extract_special_effects(
        pet,
        load_effect_descriptions(session),
    )
    if pet_data.id == SPECIAL_SOULMARK_PET_ID:
        soulmarks.append(
            {
                "id": 0,
                "desc": "登场首回合所有攻击先制+1同时增加20%暴击率",
                "intensified": True,
                "intensified_to_id": None,
                "is_adv": False,
                "pve_effective": None,
                "tags": [],
                "icon_id": None,
                "icon": None,
            }
        )
    base_soulmarks, upgraded_soulmarks = _partition_soulmarks(
        soulmarks,
        partner_data,
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
    special_skills, advanced_skills, fifth_skills, level_skills = _group_skills(
        all_skills
    )
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
    pet_skill_names = {s["name"] for s in all_skills}
    skill_mark_snapshots = _snapshot_skill_mintmarks(
        mintmarks,
        pet_skill_names,
    )
    type_ids = list({skill["type_id"] for skill in all_skills} | {pet_data.type_id})

    # Do not access lazy ORM relationships after the first await below. The
    # session can be replaced while remote image requests are in flight.
    await asyncio.gather(
        _load_activation_item_icons(images, activation_items),
        _load_pet_partner_item_icons(images, pet_partner),
    )

    (
        pet_head_bytes,
        pet_body_bytes,
        *rest_results,
    ) = await asyncio.gather(
        images.fetch("pet_head", str(pet_data.resource_id)),
        images.fetch("pet_body", str(pet_data.resource_id)),
        *(images.fetch("element_type", str(tid)) for tid in type_ids),
        images.fetch("element_type", "prop"),
        *(
            images.fetch("mintmark", str(snapshot.id))
            for snapshot in skill_mark_snapshots
        ),
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
            id=snapshot.id,
            name=snapshot.name,
            desc=snapshot.desc,
            icon=to_data_uri(icon_bytes),
            skills=list(snapshot.skills),
        )
        for snapshot, icon_bytes in zip(
            skill_mark_snapshots,
            mm_icon_results,
            strict=True,
        )
    ]

    result = await render_html(
        template_path=[CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        template_name="template.html.j2",
        templates={
            "pet_name": pet_data.name,
            "pet_id": pet_data.id,
            "pet_gender_id": pet_data.gender_id,
            "pet_gender_icon": _gender_icon_data_uri(pet_data.gender_id),
            "pet_type_id": pet_data.type_id,
            "pet_type_name": pet_data.type_name,
            "pet_head_img": to_data_uri(pet_head_bytes),
            "pet_body_img": to_data_uri(pet_body_bytes),
            "type_icons": type_icons,
            "pet_introduction": pet_data.introduction,
            "stats": stats,
            "advance_stats": advance_stats,
            "soulmarks": soulmarks,
            "base_soulmarks": base_soulmarks,
            "upgraded_soulmarks": upgraded_soulmarks,
            "pet_partner": pet_partner,
            "special_effects": special_effects,
            "skill_marks": skill_marks,
            "fifth_skills": fifth_skills[::-1],
            "advanced_skills": advanced_skills[::-1],
            "special_skills": special_skills[::-1],
            "level_skills": level_skills,
        },
        max_width=1200,
        allow_refit=False,
    )
    cache.put("custom_pet_info_v5", str(pet_id), result)
    return result
