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


SIGN_SEGMENT_COLOR = "#f35555"


def _glossary_dict(name: str, desc: str) -> GlossaryDict:
    return GlossaryDict(name=name, desc=desc, color="")


def _glossary_group_from_entry(
    entry: GlossaryEntryORM, links: tuple[GlossaryDict, ...]
) -> GlossaryGroup:
    return GlossaryGroup(
        primary=_glossary_dict(entry.name, entry.desc),
        links=links,
    )


def _subordinate_names_in(
    sign_names: list[str],
    glossary_by_name: dict[str, GlossaryEntryORM],
) -> set[str]:
    matched = set(sign_names)
    subordinates: set[str] = set()
    for name in sign_names:
        entry = glossary_by_name.get(name)
        if entry is None:
            continue
        for link in entry.link:
            if link.name in matched:
                subordinates.add(link.name)
    return subordinates


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
    sign_names: NotRequired[list[str]]


class SoulmarkDict(TypedDict):
    desc: str
    intensified: bool
    is_adv: bool
    pve_effective: bool | None
    tags: list[str]
    glossaries: list[GlossaryDict]
    glossary_groups: list[GlossaryGroup]
    sign_names: NotRequired[list[str]]
    desc_parser: NotRequired[AnalyzeDescParser]


class SkillGroups(NamedTuple):
    all_skills: list[SkillDict]
    fifth_skills: list[SkillDict]
    advanced_skills: list[SkillDict]
    special_skills: list[SkillDict]
    level_skills: list[SkillDict]
    display_skills: list[SkillDict]


class LoadedImages(NamedTuple):
    pet_head_img: str
    pet_body_img: str
    type_icons: dict[int | str, str]
    skill_marks: list[MintMarkDict]


class PetInfoRenderer:
    def __init__(self, pet: PetORM) -> None:
        self.pet = pet
        self.session = cast("Session", object_session(pet))
        assert self.session is not None
        self._color_by_name: dict[str, str] = {}
        self._glossary_by_name: dict[str, GlossaryEntryORM] = {}

    def _load_glossary_by_name(self, entry_names: set[str]) -> None:
        if not entry_names:
            self._glossary_by_name = {}
            return
        glossary_entries = self.session.exec(
            select(GlossaryEntryORM)
            .where(col(GlossaryEntryORM.name).in_(entry_names))
            .options(selectinload(GlossaryEntryORM.link))  # type: ignore[arg-type]
        ).all()
        self._glossary_by_name = {entry.name: entry for entry in glossary_entries}

    @staticmethod
    def _collect_sign_names_from_parsers(
        parsers: list[AnalyzeDescParser],
    ) -> list[str]:
        sign_names: list[str] = []
        seen: set[str] = set()
        for parser in parsers:
            for seg in parser.segments_by_color(SIGN_SEGMENT_COLOR):
                if seg.text not in seen:
                    seen.add(seg.text)
                    sign_names.append(seg.text)
        return sign_names

    def _build_glossary_groups(
        self, sign_names: list[str], seen: set[str]
    ) -> list[GlossaryGroup]:
        subordinate_names = _subordinate_names_in(sign_names, self._glossary_by_name)
        groups: list[GlossaryGroup] = []
        for name in sign_names:
            if name in subordinate_names:
                continue
            entry = self._glossary_by_name.get(name)
            if entry is None or entry.name in seen:
                continue
            seen.add(entry.name)
            links = tuple(
                _glossary_dict(linked.name, linked.desc) for linked in entry.link
            )
            for linked in entry.link:
                seen.add(linked.name)
            groups.append(_glossary_group_from_entry(entry, links))
        return groups

    def _extract_skill(self, skill_in_pet: SkillInPetORM) -> list[SkillDict]:
        skill = skill_in_pet.skill
        effects = []
        effect_parsers: list[AnalyzeDescParser] = []
        for eff in skill.skill_effect:
            parser = AnalyzeDescParser(eff.analyze_info)
            effect_parsers.append(parser)
            effects.append(
                {
                    "id": eff.effect_id,
                    "parser": parser,
                    "info": "",
                }
            )
        sign_names = self._collect_sign_names_from_parsers(effect_parsers)
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
            glossary_groups=[],
            sign_names=sign_names,
        )
        if len(skill.friend_skill_effect) > 0:
            friend_skill: SkillDict = {
                **result,
                "friend_bonus": True,
                "is_special": True,
                "effects": [
                    {"id": e.effect_id, "info": e.info}
                    for e in skill.friend_skill_effect
                ],
            }
            return [result, friend_skill]

        return [result]

    def _extract_soulmark(self, soulmarks: list[SoulmarkORM]) -> list[SoulmarkDict]:
        results: list[SoulmarkDict] = []
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

            sign_names = [
                seg.text for seg in desc_parser.segments_by_color(SIGN_SEGMENT_COLOR)
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
                    glossary_groups=[],
                    sign_names=sign_names,
                )
            )
        return results

    def _resolve_glossary_groups(
        self,
        soulmarks: list[SoulmarkDict],
        skills_in_display_order: list[SkillDict],
    ) -> None:
        all_names: set[str] = set()
        for sm in soulmarks:
            all_names.update(sm.get("sign_names", ()))
        for skill in skills_in_display_order:
            all_names.update(skill.get("sign_names", ()))
        self._load_glossary_by_name(all_names)

        seen: set[str] = set()
        for sm in soulmarks:
            sm["glossary_groups"] = self._build_glossary_groups(
                sm.get("sign_names", []), seen
            )
        for skill in skills_in_display_order:
            skill["glossary_groups"] = self._build_glossary_groups(
                skill.get("sign_names", []), seen
            )

    def _assign_glossary_colors(
        self,
        soulmarks: list[SoulmarkDict],
        skills_in_display_order: list[SkillDict],
    ) -> None:
        color_index = 0

        def color_for(name: str) -> str:
            nonlocal color_index
            if name not in self._color_by_name:
                self._color_by_name[name] = SIGN_HIGHLIGHT_COLORS[
                    color_index % len(SIGN_HIGHLIGHT_COLORS)
                ]
                color_index += 1
            return self._color_by_name[name]

        def build_glossaries(groups: list[GlossaryGroup]) -> list[GlossaryDict]:
            glossaries: list[GlossaryDict] = []
            for group in groups:
                primary_color = color_for(group.primary.name)
                for link in group.links:
                    self._color_by_name[link.name] = primary_color
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

    def _apply_glossary_highlight_colors(
        self,
        soulmarks: list[SoulmarkDict],
        skills: list[SkillDict],
    ) -> None:
        styles = _build_glossary_desc_styles(self._color_by_name)
        for sm in soulmarks:
            if desc_parser := sm.get("desc_parser"):
                sm["desc"] = desc_parser.to_html(styles)
        for skill in skills:
            for effect in skill["effects"]:
                if parser := effect.get("parser"):
                    effect["info"] = parser.to_html(styles)

    def _process_glossary(
        self,
        soulmarks: list[SoulmarkDict],
        display_skills: list[SkillDict],
        all_skills: list[SkillDict],
    ) -> None:
        self._color_by_name = {}
        self._resolve_glossary_groups(soulmarks, display_skills)
        self._assign_glossary_colors(soulmarks, display_skills)
        self._apply_glossary_highlight_colors(soulmarks, all_skills)

    def _build_soulmarks(self) -> list[SoulmarkDict]:
        soulmarks = self._extract_soulmark(self.pet.soulmark)
        if self.pet.id == 2500:
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
        return soulmarks

    def _build_skills(self) -> SkillGroups:
        all_skills: list[SkillDict] = [
            skill
            for skill_list in [self._extract_skill(sl) for sl in self.pet.skill_links]
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
            fifth_skills[::-1]
            + advanced_skills[::-1]
            + special_skills[::-1]
            + level_skills
        )
        return SkillGroups(
            all_skills=all_skills,
            fifth_skills=fifth_skills,
            advanced_skills=advanced_skills,
            special_skills=special_skills,
            level_skills=level_skills,
            display_skills=display_skills,
        )

    def _fetch_mintmarks(self, skill_ids: list[int]) -> list[MintmarkORM]:
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
                | (col(PetMintmarkLink.pet_id) == self.pet.id)
            )
            .where(
                col(PetMintmarkLink.pet_id).is_(None)
                | (col(PetMintmarkLink.pet_id) == self.pet.id)
            )
            .distinct()
        )
        return list(self.session.exec(stmt).all())

    async def _load_images(
        self,
        all_skills: list[SkillDict],
        mintmarks: list[MintmarkORM],
    ) -> LoadedImages:
        type_ids = list({skill["type_id"] for skill in all_skills} | {self.pet.type.id})
        pet_skill_names = {s["name"] for s in all_skills}

        (
            pet_head_bytes,
            pet_body_bytes,
            *rest_results,
        ) = await asyncio.gather(
            PetHeadImageGetter.get_bytes(str(self.pet.resource_id)),
            PetBodyImageGetter.get_bytes(str(self.pet.resource_id)),
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

        return LoadedImages(
            pet_head_img=to_data_uri(pet_head_bytes),
            pet_body_img=to_data_uri(pet_body_bytes),
            type_icons=type_icons,
            skill_marks=skill_marks,
        )

    def _build_template_context(
        self,
        *,
        stats: dict[str, Any],
        advance_stats: dict[str, Any] | None,
        soulmarks: list[SoulmarkDict],
        images: LoadedImages,
        skill_groups: SkillGroups,
    ) -> dict[str, Any]:
        encyclopedia = self.pet.encyclopedia
        pet_height: str | None = None
        pet_weight: str | None = None
        pet_food: str | None = None
        if encyclopedia:
            pet_height = (
                f"{encyclopedia.height:g}cm"
                if encyclopedia.height is not None
                else "未知"
            )
            pet_weight = (
                f"{encyclopedia.weight:g}kg"
                if encyclopedia.weight is not None
                else "未知"
            )
            pet_food = encyclopedia.food

        return {
            "pet_name": self.pet.name,
            "pet_id": self.pet.id,
            "pet_introduction": encyclopedia.introduction if encyclopedia else None,
            "pet_height": pet_height,
            "pet_weight": pet_weight,
            "pet_food": pet_food,
            "pet_gender_id": self.pet.gender.id,
            "pet_gender_icon": f"images/{self.pet.gender.id}.png",
            "pet_type_id": self.pet.type.id,
            "pet_type_name": self.pet.type.name,
            "pet_head_img": images.pet_head_img,
            "pet_body_img": images.pet_body_img,
            "type_icons": images.type_icons,
            "stats": stats,
            "advance_stats": advance_stats,
            "soulmarks": soulmarks,
            "skill_marks": images.skill_marks,
            "fifth_skills": skill_groups.fifth_skills[::-1],
            "advanced_skills": skill_groups.advanced_skills[::-1],
            "special_skills": skill_groups.special_skills[::-1],
            "level_skills": skill_groups.level_skills,
        }

    async def render(self) -> bytes:
        cached = render_cache.get("pet_info", str(self.pet.id))
        if cached is not None:
            return cached

        base_stats = self.pet.base_stats.to_model().round()
        stats = base_stats.model_dump()
        advance_stats = None
        if self.pet.advance:
            advance_stats = self.pet.advance.base_stats.to_model().round().model_dump()

        soulmarks = self._build_soulmarks()
        skill_groups = self._build_skills()
        self._process_glossary(
            soulmarks, skill_groups.display_skills, skill_groups.all_skills
        )

        skill_ids = [sl.skill_id for sl in self.pet.skill_links]
        mintmarks = self._fetch_mintmarks(skill_ids)
        images = await self._load_images(skill_groups.all_skills, mintmarks)

        result = await template_to_pic(
            template_path=[TEMPLATE_PATH, SHARED_PATH],
            template_name="template.html.j2",
            templates=self._build_template_context(
                stats=stats,
                advance_stats=advance_stats,
                soulmarks=soulmarks,
                images=images,
                skill_groups=skill_groups,
            ),
            max_width=1200,
            allow_refit=False,
        )
        render_cache.put("pet_info", str(self.pet.id), result)
        return result


async def render_pet_info(pet: PetORM) -> bytes:
    """渲染精灵信息卡片图片，返回 PNG 图片字节"""
    return await PetInfoRenderer(pet).render()
