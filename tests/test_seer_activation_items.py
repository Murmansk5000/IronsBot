# SPDX-License-Identifier: MIT
from types import SimpleNamespace
from typing import Any, cast

from pytest import MonkeyPatch

from ironsbot.integrations.seer_data.pet_info_repository import _load_activation_items
from ironsbot.services.seer.rendering.pet_info_models import PetItemPriceSnapshot

SPECIAL_SKILL_ITEM_ID = 1728277


def test_special_skill_uses_shop_item_when_upstream_item_is_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    price = PetItemPriceSnapshot(
        source_name="追加技能商店",
        item_name="咎者焚卷",
        item_quantity=1,
        currency_item_id=1726992,
        currency_name="共振晶体",
        amount=400,
        purchase_limit=1,
    )
    link = SimpleNamespace(
        skill_activation_item_id=SPECIAL_SKILL_ITEM_ID,
        skill_activation_item=None,
    )
    monkeypatch.setattr(
        "ironsbot.integrations.seer_data.pet_info_repository._load_item_exchange_prices",
        lambda _session, item_ids: {SPECIAL_SKILL_ITEM_ID: (price,)}
        if set(item_ids) == {SPECIAL_SKILL_ITEM_ID}
        else {},
    )

    items = _load_activation_items(cast("Any", object()), [link])

    assert items[0].id == SPECIAL_SKILL_ITEM_ID
    assert items[0].name == "咎者焚卷"
    assert items[0].prices == (price,)
