# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from seerapi_models import MintmarkORM, PetORM, SkillInPetORM, SoulmarkORM
from seerapi_models.mintmark import PetMintmarkLink, SkillMintmarkLink
from sqlalchemy.orm import object_session
from sqlmodel import col, select

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
from .custom_pet_soulmark_icons import (
    load_soulmark_icons,
    resolve_soulmark_icon_urls,
)
from .custom_pet_special_effects import (
    _add_linked_glossary_effects,
    _add_named_status_icons,
    _add_pet_linked_status_effects,
    _add_skill_red_effects,
    _add_soulmark_highlight_effects,
    _assign_special_effect_colors,
    _deduplicate_special_effects,
    _extract_special_effects,
    _sort_special_effects,
)

SPECIAL_SOULMARK_PET_ID = 2500
HIDDEN_SKILL_ID = 19002
PARTNER_UPGRADE_MIN_SIMILARITY = 0.8
PARTNER_UPGRADE_MIN_DELTA = 0.01
_RICH_TEXT_COLOR_OPEN_RE = re.compile(r"<color=(#[0-9a-fA-F]{6})>")
_RICH_TEXT_TAG_RE = re.compile(r"</?[^>]+>")
logger = logging.getLogger(__name__)


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
    effect_colors: Mapping[str, str] | None = None,
) -> list[SkillDict]:
    skill = skill_in_pet.skill
    effect_colors = effect_colors or {}
    effects = [
        {
            "id": e.effect_id,
            "info": _format_analyze_desc(e.analyze_info, effect_colors),
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
        info=_format_plain_desc(skill.info, effect_colors),
        learning_level=skill_in_pet.learning_level,
        is_special=skill_in_pet.is_special,
        is_advanced=skill_in_pet.is_advanced,
        is_fifth=skill_in_pet.is_fifth,
        effects=effects,
        activation_item=activation_item,
        friend_bonus=False,
        hide_effect_desc=_format_plain_desc(hide_effect_desc, effect_colors),
    )
    if len(skill.friend_skill_effect) > 0:
        friend_skill: SkillDict = {
            **result,
            "friend_bonus": True,
            "is_special": True,
            "effects": [
                {
                    "id": e.effect_id,
                    "info": _format_analyze_desc(
                        e.analyze_info or e.info,
                        effect_colors,
                    ),
                }
                for e in skill.friend_skill_effect
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


async def _load_special_effect_icons(
    images: SeerImageSource,
    effects: Sequence[SpecialEffectDict],
) -> None:
    icon_effects = [effect for effect in effects if effect["status_id"] is not None]
    if not icon_effects:
        return

    results = await asyncio.gather(
        *(
            fetch_optional_image(images, "sign_buff", str(effect["status_id"]))
            for effect in icon_effects
        )
    )
    for effect, result in zip(icon_effects, results, strict=True):
        if result.data is not None:
            effect["icon"] = to_data_uri(result.data)


def _extract_soulmark(
    soulmarks: list[SoulmarkORM],
    effect_colors: Mapping[str, str] | None = None,
) -> list[SoulmarkDict]:
    results: list[SoulmarkDict] = []
    # The link table has no display-order column. Soulmark IDs are allocated
    # chronologically, so use them as a stable old-to-new fallback for entries
    # that have no official upgraded-to relation.
    for sm in sorted(soulmarks, key=lambda soulmark: int(soulmark.id)):
        result = SoulmarkDict(
            id=int(sm.id),
            desc=_format_soulmark_desc(sm, effect_colors or {}),
            intensified=sm.intensified,
            intensified_to_id=sm.intensified_to_id,
            is_adv=sm.is_adv,
            pve_effective=sm.pve_effective,
            tags=[t.name for t in sm.tag] if sm.tag else [],
            icon_id=None,
            icon_asset_url=None,
            icon=None,
        )

        results.append(result)

    return results


def _format_soulmark_desc(
    soulmark: SoulmarkORM,
    effect_colors: Mapping[str, str],
) -> str:
    if soulmark.analyze_desc:
        return _format_analyze_desc(soulmark.analyze_desc, effect_colors)
    formatting = str(getattr(soulmark, "desc_formatting_adjustment", "") or "")
    if formatting:
        desc = formatting.replace("\r\n", "|").replace("\n", "|")
        desc = _RICH_TEXT_COLOR_OPEN_RE.sub(r"[color=\1]", desc)
        desc = desc.replace("</color>", "[/color]")
        desc = _RICH_TEXT_TAG_RE.sub("", desc)
        return _format_analyze_desc(desc, effect_colors)
    return _format_analyze_desc(soulmark.desc, effect_colors)


def _format_analyze_desc(value: str | None, effect_colors: Mapping[str, str]) -> str:
    return format_analyze_description(value, effect_colors)


def _format_plain_desc(
    value: str | None,
    effect_colors: Mapping[str, str],
) -> str | None:
    return format_plain_analyze_description(value, effect_colors)


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

    contained_index = _contained_partner_upgrade_index(soulmarks, after, before)
    if contained_index is not None:
        return contained_index
    return _similar_partner_upgrade_index(soulmarks, after, before)


def _contained_partner_upgrade_index(
    soulmarks: Sequence[SoulmarkDict],
    after: str,
    before: str,
) -> int | None:
    after_indexes = _contained_soulmark_indexes(soulmarks, after)
    before_indexes = _contained_soulmark_indexes(soulmarks, before)
    if not after_indexes:
        return None
    after_index = max(after_indexes, key=lambda index: soulmarks[index]["id"])
    if not before_indexes:
        return after_index
    before_index = max(before_indexes, key=lambda index: soulmarks[index]["id"])
    if soulmarks[before_index]["id"] > soulmarks[after_index]["id"]:
        # Some partner-upgrade payloads reverse the before/after fields.
        return before_index
    return after_index


def _similar_partner_upgrade_index(
    soulmarks: Sequence[SoulmarkDict],
    after: str,
    before: str,
) -> int | None:
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
    after_score, _before_score, after_index = max(
        candidates,
        key=lambda candidate: (candidate[0] - candidate[1], candidate[0]),
    )
    if after_score < PARTNER_UPGRADE_MIN_SIMILARITY:
        return None

    _after_score, before_score, before_index = max(
        candidates,
        key=lambda candidate: (candidate[1] - candidate[0], candidate[1]),
    )
    if (
        before_score >= PARTNER_UPGRADE_MIN_SIMILARITY
        and before_index != after_index
        and soulmarks[before_index]["id"] > soulmarks[after_index]["id"]
    ):
        # Some partner-upgrade payloads reverse the before/after text fields.
        # When both variants match strongly, soulmark IDs are the reliable
        # chronological fallback: the later ID is the enhanced variant.
        return before_index
    return after_index


def _contained_soulmark_indexes(
    soulmarks: Sequence[SoulmarkDict],
    partner_description: str,
) -> list[int]:
    """Find soulmarks whose complete official text occurs in a partner record."""
    if not partner_description:
        return []
    return [
        index
        for index, soulmark in enumerate(soulmarks)
        if (description := _normalize_soulmark_text(soulmark["desc"]))
        and (description in partner_description or partner_description in description)
    ]


def _normalize_soulmark_text(value: str | None) -> str:
    without_markup = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"[\W_]+", "", without_markup).casefold()


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
    cached = cache.get("custom_pet_info_v16", str(pet_id))
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
    partner_data = load_pet_partner(session, pet_id)
    pet_partner = _build_pet_partner(partner_data, session)
    special_effects = _extract_special_effects(pet)
    _add_pet_linked_status_effects(session, special_effects, pet_id=pet_id)
    _add_skill_red_effects(session, pet, special_effects)
    _add_soulmark_highlight_effects(session, pet, special_effects)
    _add_named_status_icons(session, special_effects)
    _add_linked_glossary_effects(session, special_effects)
    _add_named_status_icons(session, special_effects)
    _deduplicate_special_effects(special_effects)
    _sort_special_effects(special_effects)
    _assign_special_effect_colors(pet, special_effects)
    effect_colors = {
        effect["name"]: color
        for effect in special_effects
        if (color := effect.get("color")) is not None
    }
    soulmarks: list[SoulmarkDict] = _extract_soulmark(pet.soulmark, effect_colors)
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
                "icon_asset_url": None,
                "icon": None,
            }
        )
    base_soulmarks, upgraded_soulmarks = _partition_soulmarks(
        soulmarks,
        partner_data,
    )
    resolve_soulmark_icon_urls(session, soulmarks, pet_id=pet_id)
    all_skills: list[SkillDict] = [
        skill
        for skill_list in [
            _extract_skill(skill_link, activation_items, effect_colors)
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
        _load_special_effect_icons(images, special_effects),
        load_soulmark_icons(images, soulmarks),
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
    cache.put("custom_pet_info_v16", str(pet_id), result)
    return result
