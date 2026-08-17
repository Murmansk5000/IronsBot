# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import html
import re
from collections.abc import Callable
from typing import Any, Literal, NamedTuple, TypedDict, cast

from nonebot_plugin_htmlkit import template_to_pic
from seerapi_models import (
    GlossaryEntryORM,
    MintmarkORM,
    PetORM,
    SkillInPetORM,
    SoulmarkORM,
)
from seerapi_models.mintmark import PetMintmarkLink, SkillMintmarkLink
from sqlalchemy.orm import object_session, selectinload
from sqlmodel import Session, col, select
from typing_extensions import NotRequired

from ironsbot.plugins.get_seer_info.render._cache import render_cache
from ironsbot.plugins.seer_data.image import (
    ElementTypeImageGetter,
    MintmarkBodyImageGetter,
    PetBodyImageGetter,
    PetHeadImageGetter,
)
from ironsbot.utils.analyze_parser import AnalyzeDescParser, TextSegment
from ironsbot.utils.image import flip_image_horizontal

from ._common import TEMPLATES_PATH, to_data_uri

TEMPLATE_PATH = TEMPLATES_PATH / "pet_info"
SHARED_PATH = TEMPLATES_PATH / "_shared"

STAT_BAR_MAX_WIDTH = 120
STAT_MAX_VALUE = 200

# 印记高亮色
SIGN_HIGHLIGHT_COLORS: tuple[str, ...] = (
    "#ff9e6e",  # 珊瑚橙
    "#f5d84a",  # 琥珀金
    "#8ae878",  # 嫩绿
    "#6eebc0",  # 海沫青
    "#ff8ab8",  # 樱粉
    "#e8a0ff",  # 丁香紫
    "#ff7b7b",  # 暖绯
    "#ffd4a0",  # 杏奶油
    # "#f0ece4",  # 白
    # "#8cb4ff",  # 蓝
    # "#ff5050",  # 红
    # "#fff55a",  # 黄
    # "#a8acb4",  # 黑
)


def _build_glossary_desc_styles(
    color_by_name: dict[str, str],
) -> dict[str, Callable[[str], str]]:
    def style_sign_highlight(text: str) -> str:
        color = color_by_name.get(html.unescape(text), "#60e0ff")
        return f'<b style="color:{color}">{text}</b>'

    return {"#f35555": style_sign_highlight}


class GlossaryDict(NamedTuple):
    name: str
    desc: str
    color: str


class GlossaryGroup(NamedTuple):
    primary: GlossaryDict
    links: tuple[GlossaryDict, ...]


def _glossary_dict(name: str, desc: str) -> GlossaryDict:
    return GlossaryDict(name=name, desc=desc, color="")


class MintMarkDict(TypedDict):
    id: int
    name: str
    desc: str
    icon: str
    skills: list[str]


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
    activation_item: str | None
    friend_bonus: bool
    hide_effect_desc: str | None
    glossaries: list[GlossaryDict]
    glossary_groups: list[GlossaryGroup]


class SoulmarkDict(TypedDict):
    desc: str
    intensified: bool
    is_adv: bool
    pve_effective: bool | None
    tags: list[str]
    glossaries: list[GlossaryDict]
    glossary_groups: list[GlossaryGroup]
    desc_parser: NotRequired[AnalyzeDescParser]


def _get_glossary_entries(
    entry_names: set[str], session: Session
) -> tuple[GlossaryEntryORM, ...]:
    glossary_entries = session.exec(
        select(GlossaryEntryORM)
        .where(col(GlossaryEntryORM.name).in_(entry_names))
        .options(selectinload(GlossaryEntryORM.link))  # type: ignore[arg-type]
    ).all()

    return tuple(glossary_entries)


def _extract_skill(skill_in_pet: SkillInPetORM, *, session: Session) -> list[SkillDict]:
    skill = skill_in_pet.skill
    effects = []
    entry_names: set[str] = set()
    for eff in skill.skill_effect:
        parser = AnalyzeDescParser(eff.analyze_info)
        effects.append(
            {
                "id": eff.effect_id,
                "analyze_info": eff.analyze_info,
                "info": "",
            }
        )
        entry_names.update(seg.text for seg in parser.segments_by_color("#f35555"))

    glossary_entries = _get_glossary_entries(entry_names, session)
    glossary_groups = [
        GlossaryGroup(
            primary=_glossary_dict(entry.name, entry.desc),
            links=tuple(
                _glossary_dict(linked.name, linked.desc) for linked in entry.link
            ),
        )
        for entry in glossary_entries
    ]
    skill_activation_item = (
        skill_in_pet.skill_activation_item.name
        if skill_in_pet.skill_activation_item
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
        activation_item=skill_activation_item,
        friend_bonus=False,
        hide_effect_desc=hide_effect_desc,
        glossaries=[],
        glossary_groups=glossary_groups,
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


def _extract_soulmark(
    soulmarks: list[SoulmarkORM], *, session: Session
) -> list[SoulmarkDict]:
    processed: list[tuple[SoulmarkORM, AnalyzeDescParser, list[TextSegment]]] = []
    entry_names: set[str] = set()

    for sm in soulmarks:
        desc_parser = AnalyzeDescParser(sm.analyze_desc or sm.desc)
        for line in desc_parser.lines:
            plain_text = line.plain_text
            if re.search(r"BOSS有效|BOSS无效", plain_text, re.IGNORECASE):
                continue

            if line.sprite == "dot1":
                line.segments.append(TextSegment(text="（BOSS有效）"))
            elif line.sprite == "dot4":
                line.segments.append(TextSegment(text="（BOSS无效）"))

        sign_segments = desc_parser.segments_by_color("#f35555")
        entry_names.update(seg.text for seg in sign_segments)
        processed.append((sm, desc_parser, sign_segments))

    glossary_entries_by_name: dict[str, GlossaryEntryORM] = {}
    if entry_names:
        # signs = session.exec(
        #     select(SignORM).where(col(SignORM.name).in_(entry_names))
        # ).all()
        # sign_by_name = {sign.name: sign for sign in signs}
        glossary_entries = _get_glossary_entries(entry_names, session)
        glossary_entries_by_name = {
            glossary.name: glossary for glossary in glossary_entries
        }

    results: list[SoulmarkDict] = []
    for sm, desc_parser, sign_segments in processed:
        glossary_groups: list[GlossaryGroup] = [
            GlossaryGroup(
                primary=_glossary_dict(entry.name, entry.desc),
                links=tuple(
                    _glossary_dict(linked.name, linked.desc) for linked in entry.link
                ),
            )
            for segment in sign_segments
            if (entry := glossary_entries_by_name.get(segment.text))
        ]
        results.append(
            SoulmarkDict(
                desc="",
                desc_parser=desc_parser,
                intensified=sm.intensified,
                is_adv=sm.is_adv,
                pve_effective=sm.pve_effective,
                tags=[t.name for t in sm.tag] if sm.tag else [],
                glossaries=[],
                glossary_groups=glossary_groups,
            )
        )
    return results


def _dedupe_glossary_groups(
    groups: list[GlossaryGroup], seen: set[str]
) -> list[GlossaryGroup]:
    kept: list[GlossaryGroup] = []
    for group in groups:
        if group.primary.name in seen:
            continue
        seen.add(group.primary.name)
        for link in group.links:
            seen.add(link.name)
        kept.append(group)
    return kept


def _dedupe_glossaries_globally(
    soulmarks: list[SoulmarkDict],
    skills_in_display_order: list[SkillDict],
) -> None:
    seen: set[str] = set()
    for sm in soulmarks:
        sm["glossary_groups"] = _dedupe_glossary_groups(sm["glossary_groups"], seen)
    for skill in skills_in_display_order:
        skill["glossary_groups"] = _dedupe_glossary_groups(
            skill["glossary_groups"], seen
        )


def _assign_glossary_colors(
    soulmarks: list[SoulmarkDict],
    skills_in_display_order: list[SkillDict],
) -> dict[str, str]:
    color_by_name: dict[str, str] = {}
    color_index = 0

    def color_for(name: str) -> str:
        nonlocal color_index
        if name not in color_by_name:
            color_by_name[name] = SIGN_HIGHLIGHT_COLORS[
                color_index % len(SIGN_HIGHLIGHT_COLORS)
            ]
            color_index += 1
        return color_by_name[name]

    def build_glossaries(groups: list[GlossaryGroup]) -> list[GlossaryDict]:
        glossaries: list[GlossaryDict] = []
        for group in groups:
            primary_color = color_for(group.primary.name)
            for link in group.links:
                color_by_name[link.name] = primary_color
            glossaries.append(
                GlossaryDict(
                    name=group.primary.name,
                    desc=group.primary.desc,
                    color=primary_color,
                )
            )
            glossaries.extend(
                GlossaryDict(name=link.name, desc=link.desc, color=primary_color)
                for link in group.links
            )
        return glossaries

    for sm in soulmarks:
        sm["glossaries"] = build_glossaries(sm["glossary_groups"])
    for skill in skills_in_display_order:
        skill["glossaries"] = build_glossaries(skill["glossary_groups"])
    return color_by_name


def _apply_glossary_highlight_colors(
    soulmarks: list[SoulmarkDict],
    skills: list[SkillDict],
    color_by_name: dict[str, str],
) -> None:
    styles = _build_glossary_desc_styles(color_by_name)
    for sm in soulmarks:
        if desc_parser := sm.get("desc_parser"):
            sm["desc"] = desc_parser.to_html(styles)
    for skill in skills:
        for effect in skill["effects"]:
            if analyze_info := effect.get("analyze_info"):
                effect["info"] = AnalyzeDescParser(analyze_info).to_html(styles)


async def render_pet_info(pet: PetORM) -> bytes:
    """渲染精灵信息卡片图片，返回 PNG 图片字节"""
    cached = render_cache.get("pet_info", str(pet.id))
    if cached is not None:
        return cached
    session = cast("Session", object_session(pet))
    assert session is not None

    base_stats = pet.base_stats.to_model().round()
    stats = base_stats.model_dump()
    advance_stats = None
    if pet.advance:
        advance_stats = pet.advance.base_stats.to_model().round().model_dump()

    soulmarks: list[SoulmarkDict] = _extract_soulmark(pet.soulmark, session=session)
    if pet.id == 2500:
        soulmarks.append(
            {
                "desc": "登场首回合所有攻击先制+1同时增加20%暴击率",
                "intensified": True,
                "is_adv": False,
                "pve_effective": None,
                "tags": [],
                "glossaries": [],
                "glossary_groups": [],
            }
        )

    all_skills: list[SkillDict] = [
        skill
        for skill_list in [
            _extract_skill(sl, session=session) for sl in pet.skill_links
        ]
        for skill in skill_list
        if skill["id"] != 19002
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
    display_skills = (
        fifth_skills[::-1] + advanced_skills[::-1] + special_skills[::-1] + level_skills
    )
    _dedupe_glossaries_globally(soulmarks, display_skills)
    color_by_name = _assign_glossary_colors(soulmarks, display_skills)
    _apply_glossary_highlight_colors(soulmarks, all_skills, color_by_name)
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
    mintmarks = session.exec(stmt).all()
    pet_skill_names = {s["name"] for s in all_skills}
    type_ids = list({skill["type_id"] for skill in all_skills} | {pet.type.id})

    (
        pet_head_bytes,
        pet_body_bytes,
        *rest_results,
    ) = await asyncio.gather(
        PetHeadImageGetter.get_bytes(str(pet.resource_id)),
        PetBodyImageGetter.get_bytes(str(pet.resource_id)),
        *(ElementTypeImageGetter.get_bytes(str(tid)) for tid in type_ids),
        ElementTypeImageGetter.get_bytes("prop"),
        *(MintmarkBodyImageGetter.get_bytes(str(mm.id)) for mm in mintmarks),
    )
    pet_body_bytes = flip_image_horizontal(pet_body_bytes)

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

    encyclopedia = pet.encyclopedia
    pet_height: str | None = None
    pet_weight: str | None = None
    pet_food: str | None = None
    if encyclopedia:
        pet_height = (
            f"{encyclopedia.height:g}cm" if encyclopedia.height is not None else "未知"
        )
        pet_weight = (
            f"{encyclopedia.weight:g}kg" if encyclopedia.weight is not None else "未知"
        )
        pet_food = encyclopedia.food

    result = await template_to_pic(
        template_path=[TEMPLATE_PATH, SHARED_PATH],
        template_name="template.html.j2",
        templates={
            "pet_name": pet.name,
            "pet_id": pet.id,
            "pet_introduction": encyclopedia.introduction if encyclopedia else None,
            "pet_height": pet_height,
            "pet_weight": pet_weight,
            "pet_food": pet_food,
            "pet_gender_id": pet.gender.id,
            "pet_gender_icon": f"images/{pet.gender.id}.png",
            "pet_type_id": pet.type.id,
            "pet_type_name": pet.type.name,
            "pet_head_img": to_data_uri(pet_head_bytes),
            "pet_body_img": to_data_uri(pet_body_bytes),
            "type_icons": type_icons,
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
    render_cache.put("pet_info", str(pet.id), result)
    return result
