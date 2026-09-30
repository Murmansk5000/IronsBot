# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest
from jinja2 import Environment, FileSystemLoader

from ironsbot.services.seer.pet_info_views import (
    PetCoreSnapshot,
    PetDerivedDisplayData,
    PetInfoAssets,
    PetInfoSnapshot,
    PetItemPriceSnapshot,
    PetItemSnapshot,
    PetPartnerSnapshot,
    PetSkillEffectSnapshot,
    PetSkillSnapshot,
    PetSoulmarkDisplayAddition,
    PetSoulmarkSnapshot,
    PetSpecialEffectView,
    PetStatsSnapshot,
)
from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.pet_info_presentation import present_pet_info
from ironsbot.services.seer.rendering.pet_info_renderer import render_pet_info_document

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.seer.rendering import TemplatePath

EXPECTED_RENDER_WIDTH = 1200


@pytest.mark.parametrize("height,weight", [(None, None), (0.0, 0.0), (12.5, 20.0)])
def test_encyclopedia_header_and_food(
    height: float | None, weight: float | None
) -> None:
    snapshot = _snapshot()
    name = "很长的精灵名称" * 12
    snapshot = replace(
        snapshot,
        pet=replace(
            snapshot.pet, name=name, height=height, weight=weight, food="  能量果  "
        ),
    )
    document = present_pet_info(snapshot, _assets())
    assert document.templates["pet_height"] == (
        "未知" if height is None else f"{height:g} cm"
    )
    assert document.templates["pet_weight"] == (
        "未知" if weight is None else f"{weight:g} kg"
    )
    environment = Environment(
        loader=FileSystemLoader([CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH])
    )
    rendered = environment.get_template(document.template_name).render(
        document.templates
    )
    assert name in rendered
    assert "喜爱的食物：能量果" in rendered
    header = rendered.split('<table class="pet-info-header">', 1)[1].split(
        "</table>", 1
    )[0]
    assert "身高：" in header and "体重：" in header
    assert "喜爱的食物" not in header
    intro = rendered.split('<div class="intro-box">', 1)[1].split("</div>", 1)[0]
    assert "喜爱的食物：能量果" in intro
    assert "letter-spacing: 0" in rendered
    assert "overflow-wrap: anywhere" in rendered
    assert "scaleX" not in rendered
    assert document.templates["pet_body_img"] == "data:image/png;base64,Ym9keQ=="


@pytest.mark.parametrize("food", [None, "", "  "])
def test_empty_food_does_not_create_introduction(food: str | None) -> None:
    snapshot = _snapshot()
    document = present_pet_info(
        replace(snapshot, pet=replace(snapshot.pet, introduction="", food=food)),
        _assets(),
    )
    environment = Environment(
        loader=FileSystemLoader([CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH])
    )
    rendered = environment.get_template(document.template_name).render(
        document.templates
    )
    assert "喜爱的食物" not in rendered
    assert '<div class="sec-title">简介</div>' not in rendered


@pytest.mark.parametrize("source", ["analyze_desc", "desc", "formatting_adjustment"])
def test_soulmark_boss_validity_is_per_line(source: str) -> None:
    snapshot = _snapshot()
    description = (
        "[sprite name=dot1][color=#f35555]有效段[/color]|"
        "[sprite name=dot4]无效段|[sprite name=dot1]已写（boss无效）|"
        "普通段|[sprite name=dot2]其他标记|[sprite name=dot1]"
    )
    soulmark = replace(snapshot.soulmarks[0], desc="", pve_effective=True)
    soulmark = replace(soulmark, **{source: description})
    document = present_pet_info(replace(snapshot, soulmarks=(soulmark,)), _assets())
    soulmarks = cast("tuple[dict[str, Any], ...]", document.templates["soulmarks"])
    lines = soulmarks[0]["desc"].split("<br>")
    assert lines == [
        '<b style="color:#f35555">有效段</b>（BOSS有效）',
        "无效段（BOSS无效）",
        "已写（boss无效）",
        "普通段",
        "其他标记",
        "",
    ]


def _snapshot(*, partner: PetPartnerSnapshot | None = None) -> PetInfoSnapshot:
    item = PetItemSnapshot(
        id=100,
        name="激活道具",
        quantity=1,
        prices=(PetItemPriceSnapshot("商店", "激活道具", 1, 200, "赛尔豆", 20, None),),
    )
    skill = PetSkillSnapshot(
        id=1,
        name="测试技能",
        type_id=1,
        type_name="普通",
        category_id=3,
        category_name="属性",
        power=0,
        max_pp=5,
        accuracy=100,
        crit_rate=None,
        priority=0,
        must_hit=True,
        info="[color=#57c975]支援[/color]",
        learning_level=1,
        is_special=False,
        is_advanced=False,
        is_fifth=False,
        effects=(PetSkillEffectSnapshot(1, "支援效果", None),),
        friend_effects=(),
        activation_item_id=item.id,
        hide_effect_description=None,
    )
    return PetInfoSnapshot(
        pet=PetCoreSnapshot(1, "测试精灵", 1001, 0, 1, "普通", "介绍"),
        base_stats=PetStatsSnapshot(1, 2, 3, 4, 5, 6),
        advance_stats=None,
        skills=(skill,),
        soulmarks=(
            PetSoulmarkSnapshot(
                id=20,
                desc="强化魂印",
                analyze_desc=None,
                formatting_adjustment=None,
                intensified=True,
                intensified_to_id=None,
                is_adv=False,
                pve_effective=None,
                tags=(),
            ),
            PetSoulmarkSnapshot(
                id=10,
                desc="基础魂印",
                analyze_desc=None,
                formatting_adjustment=None,
                intensified=False,
                intensified_to_id=20,
                is_adv=False,
                pve_effective=None,
                tags=(),
            ),
        ),
        activation_items=(item,),
        partner=partner,
        skill_mintmarks=(),
        display=PetDerivedDisplayData((), ((10, 1), (20, 2)), ()),
        rich_texts=(skill.info or "",),
    )


def _assets() -> PetInfoAssets:
    return PetInfoAssets(
        gender_icon=b"gender",
        pet_head=b"head",
        pet_body=b"body",
        type_icons=((1, b"type"), ("prop", b"prop")),
        mintmark_icons=(),
        item_icons=((100, b"item"), (200, b"currency")),
        special_effect_icons=(),
    )


def test_published_variant_icon_overrides_parent_without_adding_effects() -> None:
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        display=replace(
            snapshot.display,
            special_effects=(
                PetSpecialEffectView("冥妖之悼", "第一条", 544, None, (), "191_1"),
                PetSpecialEffectView("幽迹之秘", "第二条", 545, None, (), "191_2"),
            ),
        ),
    )
    assets = replace(
        _assets(),
        special_effect_icons=(("191_1", b"first"), ("191_2", b"second")),
    )

    effects = cast(
        "tuple[dict[str, Any], ...]",
        present_pet_info(snapshot, assets).templates["special_effects"],
    )

    assert [effect["name"] for effect in effects] == ["冥妖之悼", "幽迹之秘"]
    assert [effect["icon"] for effect in effects] == [
        "data:image/png;base64,Zmlyc3Q=",
        "data:image/png;base64,c2Vjb25k",
    ]


def test_effect_partition_keeps_shared_children_and_cycles_once() -> None:
    snapshot = _snapshot()
    facts = (
        PetSpecialEffectView("Parent", "P", 1, None, (), effect_key="p"),
        PetSpecialEffectView(
            "Child",
            "C",
            2,
            None,
            ("官方关联词条",),
            effect_key="c",
            parent_effect_keys=("p", "loop"),
        ),
        PetSpecialEffectView(
            "Loop",
            "L",
            3,
            None,
            (),
            effect_key="loop",
            parent_effect_keys=("c",),
        ),
    )
    snapshot = replace(
        snapshot, display=replace(snapshot.display, special_effects=facts)
    )
    effects = cast(
        "tuple[dict[str, Any], ...]",
        present_pet_info(snapshot, _assets()).templates["special_effects"],
    )
    assert [
        (effect["name"], effect["related"], effect["parents"]) for effect in effects
    ] == [
        ("Parent", False, []),
        ("Child", True, ["Parent", "Loop"]),
        ("Loop", True, ["Child"]),
    ]
    environment = Environment(
        loader=FileSystemLoader([CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH])
    )
    html = environment.get_template("template.html.j2").render(
        **present_pet_info(snapshot, _assets()).templates
    )
    assert "直接效果" in html
    assert "关联说明" in html
    effect_section = html.split('<div class="sec-title">专属效果</div>', 1)[1]
    for name in ("Parent", "Child", "Loop"):
        assert html.count(f">{name}</span>") == 1
        assert f">{name}</span>" in effect_section


def test_presenter_builds_template_document_from_detached_values() -> None:
    document = present_pet_info(_snapshot(), _assets())

    templates = cast("Mapping[str, Any]", document.templates)
    assert templates["pet_name"] == "测试精灵"
    assert templates["stats"] == {
        "atk": 1,
        "def_": 2,
        "sp_atk": 3,
        "sp_def": 4,
        "spd": 5,
        "hp": 6,
        "total": 21,
    }
    assert [value["id"] for value in templates["soulmarks"]] == [10, 20]
    assert [value["id"] for value in templates["base_soulmarks"]] == [10]
    assert [value["id"] for value in templates["upgraded_soulmarks"]] == [20]
    skill = templates["level_skills"][0]
    assert skill["accuracy"] == "必中"
    assert skill["activation_item"]["icon"].startswith("data:image/png;base64,")


def test_presenter_uses_published_partner_upgrade_kind_for_partitioning() -> None:
    partner = PetPartnerSnapshot(
        group_id=1,
        name="测试羁绊",
        cost_item=PetItemSnapshot(300, "契约徽章", 8),
        before_description="基础魂印",
        after_description="强化魂印",
        skill=None,
    )

    snapshot = _snapshot(partner=partner)
    soulmarks = (
        replace(snapshot.soulmarks[0], intensified=False),
        replace(snapshot.soulmarks[1], intensified=False),
    )
    document = present_pet_info(
        replace(
            snapshot,
            soulmarks=soulmarks,
            display=PetDerivedDisplayData(
                snapshot.display.special_effects,
                snapshot.display.soulmark_display_order,
                snapshot.display.soulmark_icons,
                snapshot.display.soulmark_display_additions,
                ((20, "partner_upgrade"),),
            ),
        ),
        _assets(),
    )
    templates = cast("Mapping[str, Any]", document.templates)

    assert templates["pet_partner"]["name"] == "测试羁绊"
    assert [value["id"] for value in templates["base_soulmarks"]] == [10]
    assert [value["id"] for value in templates["upgraded_soulmarks"]] == [20]


def test_presenter_does_not_infer_partner_upgrade_from_descriptions() -> None:
    partner = PetPartnerSnapshot(
        group_id=1,
        name="测试羁绊",
        cost_item=PetItemSnapshot(300, "契约徽章", 8),
        before_description="基础魂印",
        after_description="强化魂印",
        skill=None,
    )
    snapshot = _snapshot(partner=partner)
    document = present_pet_info(
        replace(
            snapshot,
            soulmarks=tuple(
                replace(soulmark, intensified=False) for soulmark in snapshot.soulmarks
            ),
        ),
        _assets(),
    )
    templates = cast("Mapping[str, Any]", document.templates)

    assert [value["id"] for value in templates["base_soulmarks"]] == [10, 20]
    assert templates["upgraded_soulmarks"] == ()


def test_presenter_uses_published_soulmark_display_additions() -> None:
    snapshot = _snapshot()
    snapshot = PetInfoSnapshot(
        pet=snapshot.pet,
        base_stats=snapshot.base_stats,
        advance_stats=snapshot.advance_stats,
        skills=snapshot.skills,
        soulmarks=snapshot.soulmarks,
        activation_items=snapshot.activation_items,
        partner=snapshot.partner,
        skill_mintmarks=snapshot.skill_mintmarks,
        display=PetDerivedDisplayData(
            snapshot.display.special_effects,
            snapshot.display.soulmark_display_order,
            snapshot.display.soulmark_icons,
            (
                PetSoulmarkDisplayAddition(
                    id=0,
                    desc="构建期补充魂印",
                    analyze_desc=None,
                    formatting_adjustment=None,
                    intensified=True,
                    intensified_to_id=None,
                    is_adv=False,
                    pve_effective=None,
                    tags=(),
                ),
            ),
        ),
        rich_texts=snapshot.rich_texts,
    )

    document = present_pet_info(snapshot, _assets())
    templates = cast("Mapping[str, Any]", document.templates)

    assert [value["id"] for value in templates["soulmarks"]] == [10, 20, 0]
    assert [value["id"] for value in templates["upgraded_soulmarks"]] == [20, 0]
    assert templates["upgraded_soulmarks"][1]["desc"] == "构建期补充魂印"


@pytest.mark.asyncio
async def test_renderer_only_passes_prepared_document_to_html_port() -> None:
    document = present_pet_info(_snapshot(), _assets())
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: TemplatePath,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        captured.update(
            template_path=template_path,
            template_name=template_name,
            templates=templates,
            max_width=max_width,
            allow_refit=allow_refit,
        )
        return b"rendered"

    result = await render_pet_info_document(render_html, ["pet", "shared"], document)

    assert result == b"rendered"
    assert captured["template_name"] == "template.html.j2"
    assert captured["templates"] is document.templates
    assert captured["max_width"] == EXPECTED_RENDER_WIDTH
    assert captured["allow_refit"] is False
