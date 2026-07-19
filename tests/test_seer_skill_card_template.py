# SPDX-License-Identifier: MIT
from typing import Any, cast

from jinja2 import Environment, FileSystemLoader

from ironsbot.services.seer.render_paths import SHARED_TEMPLATE_PATH


def test_skill_card_shows_activation_item_and_exchange_price() -> None:
    environment = Environment(loader=FileSystemLoader(SHARED_TEMPLATE_PATH))
    template = environment.get_template("skill_card_macro.html.j2")
    template_module = cast("Any", template.module)
    html = str(
        template_module.skill_card(
            {
                "name": "黄泉妖偈",
                "type_id": 1,
                "category_id": 3,
                "category_name": "属性",
                "learning_level": None,
                "is_fifth": False,
                "is_special": True,
                "is_advanced": False,
                "friend_bonus": False,
                "power": 0,
                "max_pp": 1,
                "accuracy": "必中",
                "priority": 0,
                "crit_rate": None,
                "effects": [],
                "hide_effect_desc": None,
                "info": None,
                "activation_item": {
                    "id": 1728296,
                    "name": "双源魂蒂",
                    "icon": "data:image/png;base64,AA==",
                    "prices": [
                        {
                            "source_name": "战令商店",
                            "item_quantity": 1,
                            "currency_item_id": 1726710,
                            "currency_name": "共鸣锚点",
                            "amount": 2000,
                            "purchase_limit": 6,
                            "currency_icon": "data:image/png;base64,AA==",
                        }
                    ],
                },
            },
            {"prop": "prop.png", 1: "type.png"},
        )
    )

    assert "激活道具" in html
    assert "双源魂蒂" in html
    assert "战令商店" in html
    assert "共鸣锚点 × 2000" in html
    assert "限购6次" in html
    assert "sk-activation-item-icon" in html
    assert "sk-activation-currency-icon" in html
