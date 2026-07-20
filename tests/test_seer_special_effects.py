# SPDX-License-Identifier: MIT
from types import SimpleNamespace
from typing import Any, cast

from jinja2 import Environment, FileSystemLoader

from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.custom_pet_info import (
    _extract_soulmark,
    _extract_special_effects,
)


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


def test_special_effects_use_official_descriptions_when_pet_glossary_is_missing() -> (
    None
):
    pet = SimpleNamespace(
        glossary_entry=[],
        soulmark=[],
        skill_links=[
            SimpleNamespace(
                skill=_skill(
                    "黄泉妖偈",
                    "[color=#f35555]冥妖之悼[/color][color=#f35555]幽迹之秘[/color]",
                )
            )
        ],
    )

    effects = _extract_special_effects(
        cast("Any", pet),
        {
            "冥妖之悼": "自身芳华寂灭先制+1。",
            "幽迹之秘": "自身幽冥鬼甲先制+1。",
        },
    )

    assert effects == [
        {
            "name": "冥妖之悼",
            "desc": "自身芳华寂灭先制+1。",
            "sources": ["技能·黄泉妖偈"],
        },
        {
            "name": "幽迹之秘",
            "desc": "自身幽冥鬼甲先制+1。",
            "sources": ["技能·黄泉妖偈"],
        },
    ]


def test_special_effects_include_pet_linked_effectdes_entries_for_4032() -> None:
    effect_descriptions = (
        ("地葬秘法", "为自身附加200点护盾和200点护罩。"),
        ("瀚海秘法", "附加200点固定伤害并恢复等量体力。"),
        ("混沌秘法", "使对手随机1个技能的PP值归零。"),
        ("幻境秘法", "下回合攻击必定打出致命一击。"),
        ("天玄秘法", "下回合免疫大于400的攻击伤害。"),
        ("时空秘法", "下回合攻击技能先制+1。"),
    )
    pet = SimpleNamespace(
        glossary_entry=[
            SimpleNamespace(name=name, desc=description)
            for name, description in effect_descriptions
        ],
        soulmark=[
            SimpleNamespace(
                analyze_desc="每个战斗阶段结束时随机领悟六大界神的一个秘法。",
                desc="",
            )
        ],
        skill_links=[],
    )

    effects = _extract_special_effects(cast("Any", pet))

    assert effects == [
        {
            "name": name,
            "desc": description,
            "sources": ["官方专属词条"],
        }
        for name, description in effect_descriptions
    ]


def test_special_effects_do_not_duplicate_4911_effectdes_entries() -> None:
    pet = SimpleNamespace(
        glossary_entry=[
            SimpleNamespace(name="骑士决斗", desc="进入时触发骑士决斗。"),
            SimpleNamespace(name="骑士决斗·落败", desc="骑士决斗的落败状态。"),
        ],
        soulmark=[
            SimpleNamespace(
                analyze_desc=(
                    "[color=#f35555]骑士决斗[/color]"
                    "[color=#f35555]骑士决斗·落败[/color]"
                ),
                desc="",
            )
        ],
        skill_links=[],
    )

    effects = _extract_special_effects(cast("Any", pet))

    assert effects == [
        {
            "name": "骑士决斗",
            "desc": "进入时触发骑士决斗。",
            "sources": ["魂印"],
        },
        {
            "name": "骑士决斗·落败",
            "desc": "骑士决斗的落败状态。",
            "sources": ["魂印"],
        },
    ]


def test_soulmark_does_not_repeat_glossary_descriptions() -> None:
    soulmark = SimpleNamespace(
        id=1,
        analyze_desc="[color=#f35555]蜃楼[/color]",
        desc="蜃楼",
        intensified=False,
        intensified_to_id=None,
        is_adv=False,
        pve_effective=False,
        tag=[],
    )

    rendered = _extract_soulmark([cast("Any", soulmark)])

    assert "glossaries" not in rendered[0]


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
    special_effect_css = html.split(".special-effect {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "background-color: #2a5a9a;" in special_effect_css
    assert "border-left: 4px solid #ffffff;" in special_effect_css
    assert ".sm-glossaries" not in html


def test_partner_upgrade_template_combines_requirements_and_soulmark() -> None:
    environment = Environment(
        loader=FileSystemLoader([CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH])
    )
    template = environment.get_template("template.html.j2")

    html = template.render(
        pet_name="倪克斯",
        pet_id=4329,
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
        base_soulmarks=[
            {
                "desc": "基础魂印说明",
                "intensified": False,
                "is_adv": False,
                "pve_effective": None,
                "tags": [],
                "icon": None,
            }
        ],
        upgraded_soulmarks=[
            {
                "desc": "强化后的魂印说明",
                "intensified": True,
                "is_adv": False,
                "pve_effective": None,
                "tags": [],
                "icon": None,
            }
        ],
        pet_partner={
            "name": "源初之夜",
            "cost_item": {
                "id": 1722827,
                "name": "契约徽章",
                "quantity": 8,
                "icon": None,
                "prices": [],
            },
            "skill": {
                "id": 36696,
                "name": "至暗·无量空邃",
                "activation_item": {
                    "id": 1725370,
                    "name": "梦夜之源",
                    "quantity": 1,
                    "icon": None,
                    "prices": [
                        {
                            "source_name": "微光秘境",
                            "item_quantity": 1,
                            "currency_item_id": 1726992,
                            "currency_name": "共振晶体",
                            "amount": 200,
                            "purchase_limit": 1,
                            "currency_icon": None,
                        }
                    ],
                },
            },
        },
        special_effects=[],
        skill_marks=[],
        fifth_skills=[],
        advanced_skills=[],
        special_skills=[],
        level_skills=[],
    )

    assert "源初之夜" in html
    expected_soulmark_count = 2
    assert html.count('class="sm-item"') == expected_soulmark_count
    assert html.count('class="sm-upgrade-title"') == 1
    assert html.index("基础魂印说明") < html.index("源初之夜")
    assert "开启消耗" in html
    assert "契约徽章 × 8" in html
    assert "技能开启道具" in html
    assert "梦夜之源 × 1" not in html
    assert "微光秘境：" in html
    assert "共振晶体 × 200" in html
    activation_item_count = 2
    assert html.count('class="sk-activation-item"') == activation_item_count
    assert "契约羁绊" not in html
    assert "升级后魂印" not in html
    assert "羁绊伙伴" not in html
    assert "羁绊新增技能" not in html
