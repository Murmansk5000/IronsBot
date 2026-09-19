# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

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
    PetStatsSnapshot,
)
from ironsbot.services.seer.rendering.pet_info_presentation import present_pet_info
from ironsbot.services.seer.rendering.pet_info_renderer import render_pet_info_document

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.seer.rendering import TemplatePath

EXPECTED_RENDER_WIDTH = 1200


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
