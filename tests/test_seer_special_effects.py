# SPDX-License-Identifier: MIT
from types import SimpleNamespace
from typing import Any, cast

from jinja2 import Environment, FileSystemLoader

from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.custom_pet_info import _extract_special_effects


def _skill(
    name: str,
    description: str,
    *,
    skill_id: int = 1,
) -> Any:
    return SimpleNamespace(
        id=skill_id,
        name=name,
        info=None,
        skill_effect=[SimpleNamespace(analyze_info=description, info=description)],
        friend_skill_effect=[],
        hide_effect=None,
    )


def test_special_effects_merge_soulmark_and_skill_sources() -> None:
    pet = SimpleNamespace(
        glossary_entry=[
            SimpleNamespace(name="蜃楼", desc="使对手进入蜃楼状态。"),
            SimpleNamespace(name="天烬海", desc="造成额外天烬海效果。"),
        ],
        soulmark=[
            SimpleNamespace(
                analyze_desc="[color=#F35555]蜃楼[/color]",
                desc="",
            )
        ],
        skill_links=[
            SimpleNamespace(
                skill=_skill(
                    "潮汐回响",
                    "[color=#f35555]蜃楼[/color][color=#f35555]天烬海[/color]",
                )
            )
        ],
    )

    effects = _extract_special_effects(cast("Any", pet))

    assert effects == [
        {
            "name": "蜃楼",
            "desc": "使对手进入蜃楼状态。",
            "sources": ["魂印", "技能·潮汐回响"],
        },
        {
            "name": "天烬海",
            "desc": "造成额外天烬海效果。",
            "sources": ["技能·潮汐回响"],
        },
    ]


def test_special_effect_template_shows_name_source_and_description() -> None:
    environment = Environment(
        loader=FileSystemLoader([CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH])
    )
    template = environment.get_template("template.html.j2")

    html = template.render(
        pet_name="测试精灵",
        pet_id=1,
        pet_gender_id=0,
        pet_gender_icon="gender.png",
        pet_type_id=1,
        pet_type_name="普通",
        pet_head_img="head.png",
        pet_body_img="body.png",
        type_icons={1: "type.png", "prop": "prop.png"},
        pet_introduction="",
        stats={
            "atk": 1,
            "def_": 1,
            "sp_atk": 1,
            "sp_def": 1,
            "spd": 1,
            "hp": 1,
            "total": 6,
        },
        advance_stats=None,
        soulmarks=[],
        special_effects=[
            {
                "name": "蜃楼",
                "desc": "使对手进入蜃楼状态。",
                "sources": ["魂印", "技能·潮汐回响"],
            }
        ],
        skill_marks=[],
        fifth_skills=[],
        advanced_skills=[],
        special_skills=[],
        level_skills=[],
    )

    assert "专属效果" in html
    assert "蜃楼" in html
    assert "魂印、技能·潮汐回响" in html
    assert "使对手进入蜃楼状态。" in html
