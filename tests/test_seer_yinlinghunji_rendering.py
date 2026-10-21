# SPDX-License-Identifier: MIT
"""Detached real-data regression; CI needs only the small checked-in JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from jinja2 import Environment, FileSystemLoader

from ironsbot.services.seer.pet_info_views import (
    PetCoreSnapshot,
    PetDerivedDisplayData,
    PetInfoAssets,
    PetInfoSnapshot,
    PetSkillEffectSnapshot,
    PetSkillSnapshot,
    PetSoulmarkSnapshot,
    PetSpecialEffectView,
    PetStatsSnapshot,
)
from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.pet_info_presentation import present_pet_info

FIXTURE = Path(__file__).parent / "fixtures" / "pet_info" / "yinlinghunji_3488.json"
PET_ID = 3488
SOULMARK_ID = 796


def _snapshot() -> PetInfoSnapshot:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    skills = tuple(
        PetSkillSnapshot(
            **{
                **row,
                "effects": tuple(
                    PetSkillEffectSnapshot(**effect) for effect in row["effects"]
                ),
                "friend_effects": tuple(
                    PetSkillEffectSnapshot(**effect) for effect in row["friend_effects"]
                ),
            }
        )
        for row in data["skills"]
    )
    soulmarks = tuple(
        PetSoulmarkSnapshot(**{**row, "tags": tuple(row["tags"])})
        for row in data["soulmarks"]
    )
    effects = tuple(
        PetSpecialEffectView(
            **{
                **row,
                "sources": tuple(row["sources"]),
                "parent_effect_keys": tuple(row["parent_effect_keys"]),
            }
        )
        for row in data["special_effects"]
    )
    # Only the selected real records participate; unrelated sections are omitted.
    rich_texts = tuple(
        text
        for skill in skills
        for text in (
            skill.info,
            *(effect.analyze_info or effect.info for effect in skill.effects),
        )
        if text
    ) + tuple(soulmark.desc for soulmark in soulmarks)
    return PetInfoSnapshot(
        pet=PetCoreSnapshot(**data["pet"]),
        base_stats=PetStatsSnapshot(**data["base_stats"]),
        advance_stats=None,
        skills=skills,
        soulmarks=soulmarks,
        activation_items=(),
        partner=None,
        skill_mintmarks=(),
        display=PetDerivedDisplayData(effects, (), ()),
        rich_texts=rich_texts,
    )


@pytest.mark.parametrize("effect_icons_available", [True, False])
def test_real_yinlinghunji_skill_soulmark_and_exclusive_effect_rendering(
    *,
    effect_icons_available: bool,
) -> None:
    snapshot = _snapshot()
    assert snapshot.pet.id == PET_ID and snapshot.pet.name == "阴灵魂姬"
    assert {skill.id: skill.name for skill in snapshot.skills} == {
        29402: "黄泉妖偈",
        31391: "冥·十刀弑魂",
        38462: "瑰·极天阴谕",
        38463: "瑰·伏心命朽",
    }
    assert snapshot.soulmarks[0].id == SOULMARK_ID
    assert snapshot.soulmarks[0].pve_effective is False
    # Asset bytes are deliberate test substitutes; the fixture contains no media.
    assets = PetInfoAssets(
        gender_icon=b"gender",
        pet_head=b"head",
        pet_body=b"body",
        type_icons=tuple((key, b"type") for key in (8, 14, 19, 62, "prop")),
        mintmark_icons=(),
        item_icons=(),
        special_effect_icons=(("191_1", b"effect-one"), ("191_2", b"effect-two"))
        if effect_icons_available
        else (),
    )
    document = present_pet_info(snapshot, assets)
    values = cast("dict[str, Any]", dict(document.templates))
    assert [skill["id"] for skill in values["special_skills"]] == [29402]
    assert {skill["id"] for skill in values["fifth_skills"]} == {31391, 38462, 38463}
    assert [soulmark["id"] for soulmark in values["base_soulmarks"]] == [SOULMARK_ID]
    assert values["upgraded_soulmarks"] == ()
    assert "150" in values["soulmarks"][0]["desc"]
    assert "250" in values["soulmarks"][0]["desc"]
    assert "boss无效" in values["soulmarks"][0]["desc"].lower()
    effects = {effect["name"]: effect for effect in values["special_effects"]}
    assert set(effects) == {"吸取体力", "冥妖之悼", "幽迹之秘"}
    for name, transformed_skill in (
        ("冥妖之悼", "瑰·极天阴谕"),
        ("幽迹之秘", "瑰·伏心命朽"),
    ):
        assert effects[name]["sources"] == ["技能·黄泉妖偈"]
        assert transformed_skill in effects[name]["desc"]
        assert bool(effects[name]["icon"]) == effect_icons_available
    html = (
        Environment(
            loader=FileSystemLoader(
                [
                    CUSTOM_PET_INFO_TEMPLATE_PATH,
                    SHARED_TEMPLATE_PATH,
                ]
            )
        )
        .get_template(document.template_name)
        .render(document.templates)
    )
    assert "阴灵魂姬" in html and "171 cm" in html and "47 kg" in html
    assert "黄泉妖偈" in html and "冥·十刀弑魂" in html
    assert "瑰·极天阴谕" in html and "瑰·伏心命朽" in html
    section = html.split('<div class="sec-title">专属效果</div>', 1)[1]
    for name in ("冥妖之悼", "幽迹之秘"):
        assert html.count(f">{name}</span>") == 1
        assert f">{name}</span>" in section
    assert "[sprite" not in html and "[color=" not in html
