# SPDX-License-Identifier: MIT
from types import SimpleNamespace
from typing import Any, cast

from pytest import MonkeyPatch

from ironsbot.services.seer.item_exchange_price import ItemExchangePrice
from ironsbot.services.seer.rendering.custom_pet_info import (
    _build_activation_items,
    _extract_skill,
)


def test_soul_emperor_special_skill_uses_shop_item_when_upstream_item_is_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    skill = SimpleNamespace(
        id=38455,
        name="魂·罪恶支骸",
        type=SimpleNamespace(id=1, name="普通"),
        category=SimpleNamespace(id=3, name="属性"),
        power=0,
        max_pp=1,
        must_hit=True,
        accuracy=100,
        crit_rate=None,
        priority=0,
        info=None,
        skill_effect=[],
        friend_skill_effect=[],
        hide_effect=None,
    )
    skill_link = SimpleNamespace(
        skill=skill,
        skill_activation_item_id=1728277,
        skill_activation_item=None,
        learning_level=None,
        is_special=True,
        is_advanced=False,
        is_fifth=False,
    )
    price = ItemExchangePrice(
        source_name="追加技能商店",
        item_name="咎者焚卷",
        item_quantity=1,
        currency_item_id=1726992,
        currency_name="共振晶体",
        amount=400,
        purchase_limit=1,
    )

    monkeypatch.setattr(
        "ironsbot.services.seer.rendering.custom_pet_info.load_item_exchange_prices",
        lambda _session, item_ids: {1728277: [price]}
        if set(item_ids) == {1728277}
        else {},
    )
    activation_items = _build_activation_items(
        cast("Any", SimpleNamespace(skill_links=[skill_link])),
        object(),
    )
    rendered_skill = _extract_skill(cast("Any", skill_link), activation_items)[0]

    assert rendered_skill["activation_item"] == {
        "id": 1728277,
        "name": "咎者焚卷",
        "icon": None,
        "prices": [
            {
                "source_name": "追加技能商店",
                "item_quantity": 1,
                "currency_item_id": 1726992,
                "currency_name": "共振晶体",
                "amount": 400,
                "purchase_limit": 1,
                "currency_icon": None,
            }
        ],
    }
