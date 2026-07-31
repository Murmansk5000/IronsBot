from typing import Literal

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.seer.query.commands.data_queries import (
    _autocard_sanctuary_effect_detail,
    _item_description,
)
from ironsbot.services.seer.new_content import NewContentItem


def _effect(
    *, change_kind: Literal["added", "modified"] = "added"
) -> NewContentItem:
    return NewContentItem(
        category="autocard_sanctuary_effect",
        entity_id=9,
        name="潮涌",
        sort_value=9,
        payload={
            "sanctuary_id": 2,
            "sanctuary_name": "沧岚",
            "sanctuary_pet_id": 3105,
            "sanctuary_pet_name": "精灵王测试",
            "unlock_round": 5,
            "buff_id": "50041",
            "buff_param": "2",
            "description": "测试效果",
        },
        change_kind=change_kind,
    )


def test_sanctuary_effect_list_preserves_sanctuary_context() -> None:
    assert _item_description(_effect()) == (
        "新增｜沧岚｜精灵王：精灵王测试｜第 5 回合祝印"
    )


def test_sanctuary_effect_detail_explains_blessing_context() -> None:
    detail = _autocard_sanctuary_effect_detail(_effect(change_kind="modified"))

    assert "状态：修改" in detail
    assert "圣域：沧岚" in detail
    assert "阶段：第 5 回合祝印" in detail
    assert "关联精灵王：精灵王测试（3105）" in detail
    assert "关联 Buff：50041（参数：2）" in detail
