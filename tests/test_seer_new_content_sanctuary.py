import asyncio
from typing import Literal

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.onebot.seer.query.commands.new_content import (
    _content_prompt,
    _render_content_prompt,
)
from ironsbot.services.seer.new_content import (
    AUTOCARD_NEW_CONTENT_CATEGORIES,
    NewContentItem,
    NewContentSnapshot,
    NewContentSnapshotChangedError,
    format_new_content_item_description,
)
from ironsbot.services.seer.new_content_details import (
    format_new_content_autocard_sanctuary_effect_detail,
    format_new_content_skill_detail,
)
from ironsbot.services.seer.new_content_menu import (
    NewContentMenuLayout,
    focus_new_content_category,
)
from tests.helpers.onebot_events import group_message_event


def _effect(*, change_kind: Literal["added", "modified"] = "added") -> NewContentItem:
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
    assert format_new_content_item_description(_effect()) == (
        "新增｜沧岚｜精灵王：精灵王测试｜第 5 回合祝印"
    )


def test_sanctuary_effect_detail_explains_blessing_context() -> None:
    detail = format_new_content_autocard_sanctuary_effect_detail(
        _effect(change_kind="modified")
    )

    assert "状态：修改" in detail
    assert "圣域：沧岚" in detail
    assert "阶段：第 5 回合祝印" in detail
    assert "关联精灵王：精灵王测试（3105）" in detail
    assert "关联 Buff：50041（参数：2）" in detail


def test_new_skill_detail_includes_effect_and_linked_pet() -> None:
    skill = NewContentItem(
        category="skill",
        entity_id=38474,
        name="测试技能",
        sort_value=38474,
        payload={
            "power": 150,
            "max_pp": 5,
            "accuracy": 95,
            "priority": 1,
            "info": "测试效果",
            "pets": [{"id": 4927, "name": "超级噗纽", "is_fifth": True}],
        },
    )

    assert format_new_content_item_description(skill) == "新增｜38474｜超级噗纽"
    detail = format_new_content_skill_detail(skill)
    assert "威力：150｜PP：5" in detail
    assert "效果：测试效果" in detail
    assert "超级噗纽（4927）（第五技能）" in detail


def test_new_autocard_prompt_includes_sanctuary_effects() -> None:
    card = NewContentItem(
        category="autocard_card",
        entity_id=98,
        name="测试卡牌",
        sort_value=98,
        payload={},
    )
    role = NewContentItem(
        category="autocard_role",
        entity_id=7,
        name="测试角色",
        sort_value=7,
        payload={},
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(card, role, _effect()),
    )

    prompt = _content_prompt(
        snapshot,
        NewContentMenuLayout(
            display_categories=AUTOCARD_NEW_CONTENT_CATEGORIES,
        ),
    )

    assert [item.name for item in prompt.items] == [
        "▶ 新增群星牌",
        "▶ 新增群星牌角色",
        "▶ 新增群星牌圣域",
    ]


def test_new_content_root_menu_only_lists_categories() -> None:
    pet = NewContentItem(
        category="pet",
        entity_id=4927,
        name="超级噗纽",
        sort_value=4927,
        payload={},
    )
    skill = NewContentItem(
        category="skill",
        entity_id=38474,
        name="金属缠绕",
        sort_value=38474,
        payload={},
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(pet, skill),
    )

    prompt = _content_prompt(
        snapshot,
        NewContentMenuLayout(
            display_categories=("pet", "skill"),
        ),
    )

    assert [item.name for item in prompt.items if item.is_visible] == [
        "▶ 新增精灵",
        "▶ 新增技能",
    ]
    assert prompt.get_item_by_input("a1") is None
    assert prompt.get_item_by_input("b1") is None
    assert "a1. 超级噗纽" not in prompt.build_message()
    assert "a. ▶ 新增精灵（1 项）" in prompt.build_message()


def test_new_content_category_selection_opens_a_numeric_menu() -> None:
    pet = NewContentItem(
        category="pet",
        entity_id=4927,
        name="超级噗纽",
        sort_value=4927,
        payload={},
    )
    skill = NewContentItem(
        category="skill",
        entity_id=38474,
        name="金属缠绕",
        sort_value=38474,
        payload={},
    )
    achievement = NewContentItem(
        category="achievement",
        entity_id=6171016,
        name="深海之泪",
        sort_value=6171016,
        payload={"point": 10},
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(pet, skill, achievement),
    )
    root_layout = NewContentMenuLayout(
        display_categories=("pet", "skill", "achievement"),
    )
    layout = focus_new_content_category(root_layout, "achievement")

    prompt = _content_prompt(snapshot, layout)

    assert prompt.title == "🆕【新增成就】输入编号查看详情：\n"
    assert "1. 深海之泪" in prompt.build_message()
    assert "a. ▶ 新增精灵" not in prompt.build_message()
    assert "b. ▶ 新增技能" not in prompt.build_message()
    assert prompt.get_item_by_input("1") is not None
    assert prompt.get_item_by_input("c1") is None


def test_new_pet_category_uses_plain_numeric_choices() -> None:
    first = NewContentItem(
        category="pet",
        entity_id=4927,
        name="超级噗纽",
        sort_value=4927,
        payload={},
    )
    second = NewContentItem(
        category="pet",
        entity_id=4928,
        name="维克佐斯",
        sort_value=4928,
        payload={},
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(first, second),
    )

    prompt = _content_prompt(
        snapshot,
        NewContentMenuLayout(
            display_categories=("pet",),
            focused_category="pet",
        ),
    )

    assert "1. 超级噗纽" in prompt.build_message()
    assert "2. 维克佐斯" in prompt.build_message()
    assert prompt.get_item_by_input("a1") is None


def test_new_content_category_shortcut_uses_numeric_keys() -> None:
    pet = NewContentItem(
        category="pet",
        entity_id=4927,
        name="超级噗纽",
        sort_value=4927,
        payload={},
    )
    skill = NewContentItem(
        category="skill",
        entity_id=38474,
        name="金属缠绕",
        sort_value=38474,
        payload={},
    )
    achievement = NewContentItem(
        category="achievement",
        entity_id=6171016,
        name="深海之泪",
        sort_value=6171016,
        payload={"point": 10},
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(pet, skill, achievement),
    )
    layout = NewContentMenuLayout(
        display_categories=("achievement",),
        focused_category="achievement",
    )

    prompt = _content_prompt(snapshot, layout)

    assert "a. " not in prompt.build_message()
    assert "b. " not in prompt.build_message()
    assert "1. 深海之泪" in prompt.build_message()


@pytest.mark.parametrize(
    "render_error", [RuntimeError, NewContentSnapshotChangedError, None]
)
def test_menu_image_and_text_fallback_share_layout_and_sender(
    render_error: type[Exception] | None,
) -> None:
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260904",
        weekly_cycle="2026-09-04",
        items=(_effect(),),
    )
    layout = NewContentMenuLayout(
        display_categories=("autocard_sanctuary_effect",),
        focused_category="autocard_sanctuary_effect",
    )
    event = group_message_event("新增群星牌圣域")
    prompt = _content_prompt(snapshot, layout)
    renderer_calls: list[tuple[object, ...]] = []

    async def renderer(*args: object) -> bytes:
        renderer_calls.append(args)
        if render_error is not None:
            raise render_error
        return b"test image"

    message = asyncio.run(
        _render_content_prompt(prompt, snapshot, layout, renderer, event)
    )

    assert isinstance(message, Message)
    assert message[0].type == "at"
    assert message[0].data["qq"] == str(event.user_id)
    assert renderer_calls[0][:3] == (
        snapshot,
        layout.display_categories,
        layout.focused_category,
    )
    selection = prompt.get_item_by_input("1")
    assert selection is not None and selection.value.item == snapshot.items[0]
    if render_error is not None:
        assert "1. 潮涌" in message.extract_plain_text()
        assert "0.【退出】" in message.extract_plain_text()
    else:
        assert message[-1].type == "image"
