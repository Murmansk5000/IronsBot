from dataclasses import replace

import pytest
from jinja2 import Environment, FileSystemLoader

from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.pet_info_presentation import present_pet_info
from tests.test_seer_pet_info_presentation import _assets, _snapshot


@pytest.mark.parametrize("height,weight", [(None, None), (0.0, 0.0), (12.5, 20.0)])
def test_encyclopedia_values_in_detached_header(
    height: float | None, weight: float | None
) -> None:
    snapshot = _snapshot()
    name = "完整长名称" * 12
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
    html = environment.get_template(document.template_name).render(document.templates)
    assert name in html and "喜爱的食物：能量果" in html
    header = html.split('<table class="pet-info-header">', 1)[1].split("</table>", 1)[0]
    assert "身高：" in header and "体重：" in header
    assert "喜爱的食物" not in header
    intro = html.split('<div class="intro-box">', 1)[1].split("</div>", 1)[0]
    assert "喜爱的食物：能量果" in intro
    assert "letter-spacing: 0" in html and "overflow-wrap: anywhere" in html
    assert "scaleX" not in html


@pytest.mark.parametrize("food", [None, "", "  "])
def test_empty_food_does_not_create_intro(food: str | None) -> None:
    snapshot = _snapshot()
    document = present_pet_info(
        replace(snapshot, pet=replace(snapshot.pet, introduction="", food=food)),
        _assets(),
    )
    environment = Environment(
        loader=FileSystemLoader([CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH])
    )
    html = environment.get_template(document.template_name).render(document.templates)
    assert "喜爱的食物" not in html
    assert '<div class="sec-title">简介</div>' not in html
