import asyncio
from typing import Any, Literal
from unittest.mock import AsyncMock

import nonebot
import pytest
from pydantic import ValidationError

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.models.seer import SeerConfig
from ironsbot.plugins.seer.query.commands.data_queries import (
    NEW_CONTENT_MENU_LAYOUT_KEY,
    NEW_CONTENT_SERVICES_KEY,
    NEW_CONTENT_SNAPSHOT_KEY,
    _autocard_sanctuary_effect_detail,
    _content_prompt,
    _focus_new_content_category,
    _item_description,
    _NewContentMenuLayout,
    _NewContentServices,
    _render_content_prompt_with_notice,
    _replace_prompt,
    _select_standard_item,
    _skill_detail,
)
from ironsbot.services.seer.new_content import (
    AUTOCARD_NEW_CONTENT_CATEGORIES,
    NewContentItem,
    NewContentSnapshot,
)
from tests.helpers.onebot_events import group_message_event


def test_new_content_expanded_categories_are_validated_and_deduplicated() -> None:
    config = SeerConfig.model_validate(
        {"new_content": {"expanded_categories": ["pet", "skill", "pet"]}}
    )

    assert config.new_content.expanded_categories == ["pet", "skill"]
    assert config.new_content.auto_expand_max_items > 0

    with pytest.raises(ValidationError, match="expanded_categories"):
        SeerConfig.model_validate(
            {"new_content": {"expanded_categories": ["unknown"]}}
        )


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


@pytest.mark.asyncio
async def test_peak_pool_item_selection_opens_pet_details() -> None:
    pet = AsyncMock()
    pet.select_info.return_value = "pet-details"
    services = _NewContentServices(
        pet=pet,
        mintmark=AsyncMock(),
        equipment=AsyncMock(),
        autocard=AsyncMock(),
        menu_renderer=AsyncMock(),
    )
    item = NewContentItem(
        "peak_pool",
        5000,
        "圣灵谱尼",
        5000,
        {"previous_limit": 0, "current_limit": 2},
        "modified",
    )

    result = await _select_standard_item(item, services)

    assert result == "pet-details"
    pet.select_info.assert_awaited_once_with(5000)
    services.equipment.select.assert_not_awaited()


class _RecordingMatcher:
    def __init__(self, state: dict[str, object] | None = None) -> None:
        self.state = {} if state is None else state
        self.sent: list[object] = []

    async def send(self, message: object) -> dict[str, int]:
        self.sent.append(message)
        return {"message_id": len(self.sent)}

    async def finish(self, message: object) -> None:
        raise AssertionError(message)


def _render_prompt_state() -> tuple[
    NewContentSnapshot,
    _NewContentMenuLayout,
    Any,
]:
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(_effect(),),
    )
    layout = _NewContentMenuLayout(
        display_categories=("autocard_sanctuary_effect",),
        focused_category="autocard_sanctuary_effect",
    )

    async def renderer(*_args: object) -> bytes:
        return b"menu-image"

    return snapshot, layout, renderer


def test_new_content_initial_render_sends_notice_before_menu_image() -> None:
    snapshot, layout, renderer = _render_prompt_state()
    matcher = _RecordingMatcher()
    event = group_message_event(user_id=123)
    prompt = _content_prompt(snapshot, layout)

    rendered = asyncio.run(
        _render_content_prompt_with_notice(
            prompt,
            snapshot,
            layout,
            renderer,
            event,
            matcher,  # type: ignore[arg-type]
        )
    )

    assert len(matcher.sent) == 1
    assert "正在生成新增内容图片" in str(matcher.sent[0])
    assert "[CQ:image" in str(rendered)


def test_new_content_category_render_sends_notice_before_replacement_menu(
    monkeypatch: Any,
) -> None:
    snapshot, layout, renderer = _render_prompt_state()
    prompt = _content_prompt(snapshot, layout)
    matcher = _RecordingMatcher(
        {
            NEW_CONTENT_SNAPSHOT_KEY: snapshot,
            NEW_CONTENT_MENU_LAYOUT_KEY: layout,
            NEW_CONTENT_SERVICES_KEY: _NewContentServices(
                pet=object(),
                mintmark=object(),
                equipment=object(),
                autocard=object(),
                menu_renderer=renderer,
            ),
        }
    )
    anchors: list[object] = []
    monkeypatch.setattr(
        "ironsbot.plugins.seer.query.commands.data_queries.update_queued_menu_anchor",
        lambda _matcher, _event, send_result, *, page_id=None: anchors.append(
            (send_result, page_id)
        ),
    )

    asyncio.run(_replace_prompt(matcher, group_message_event(), prompt))  # type: ignore[arg-type]

    assert "正在生成新增内容图片" in str(matcher.sent[0])
    assert "[CQ:image" in str(matcher.sent[1])
    assert anchors == [({"message_id": 2}, prompt.page_id)]


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

    assert _item_description(skill) == "新增｜38474｜超级噗纽"
    detail = _skill_detail(skill)
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
        _NewContentMenuLayout(
            display_categories=AUTOCARD_NEW_CONTENT_CATEGORIES,
            expanded_categories=frozenset(AUTOCARD_NEW_CONTENT_CATEGORIES),
        ),
    )

    assert prompt.title == "🆕【新增群星牌】输入编号查看详情：\n"
    assert [item.name for item in prompt.items if item.is_visible] == [
        "▼ 新增群星牌",
        "测试卡牌",
        "▼ 新增群星牌角色",
        "测试角色",
        "▼ 新增群星牌圣域",
        "潮涌",
    ]


def test_new_content_root_menu_uses_configured_explicit_item_keys() -> None:
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
        _NewContentMenuLayout(
            display_categories=("pet", "skill"),
            expanded_categories=frozenset({"pet"}),
            auto_expand_max_items=0,
        ),
    )

    assert [item.name for item in prompt.items if item.is_visible] == [
        "▼ 新增精灵",
        "超级噗纽",
        "▶ 新增技能",
    ]
    first_item = prompt.get_item_by_input("a1")
    second_item = prompt.get_item_by_input("b1")
    assert first_item is not None and first_item.value.item == pet
    assert second_item is not None and second_item.value.item == skill
    assert "a1. 超级噗纽" in prompt.build_message()
    assert "a. ▼ 新增精灵（1 项新增）" in prompt.build_message()


def test_new_content_root_menu_keeps_folded_items_selectable() -> None:
    pet = NewContentItem(
        category="pet",
        entity_id=4927,
        name="超级噗纽",
        sort_value=4927,
        payload={},
    )
    skills = tuple(
        NewContentItem(
            category="skill",
            entity_id=38000 + index,
            name=f"技能 {index}",
            sort_value=38000 + index,
            payload={},
        )
        for index in range(1, 7)
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(pet, *skills),
    )

    prompt = _content_prompt(
        snapshot,
        _NewContentMenuLayout(
            display_categories=("pet", "skill"),
            auto_expand_max_items=0,
        ),
    )

    assert [item.key for item in prompt.items if item.is_visible] == ["a", "b"]
    first_item = prompt.get_item_by_input("a1")
    skill_category = prompt.get_item_by_input("b")
    assert first_item is not None and first_item.value.item == pet
    assert all(
        prompt.get_item_by_input(f"b{index}") is not None
        for index in range(1, 7)
    )
    assert skill_category is not None and skill_category.value.category == "skill"


def test_new_content_root_menu_auto_expands_short_categories() -> None:
    pet = NewContentItem("pet", 4927, "超级噗纽", 4927, {})
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260731",
        weekly_cycle="2026-07-31",
        items=(pet,),
    )

    prompt = _content_prompt(
        snapshot,
        _NewContentMenuLayout(display_categories=("pet",)),
    )

    assert "a. ▼ 新增精灵（1 项新增）" in prompt.build_message()
    assert "a1. 超级噗纽" in prompt.build_message()


def test_new_content_root_menu_separates_added_and_modified_counts() -> None:
    pet = NewContentItem("pet", 4929, "鬼地行者", 4929, {})
    skills = tuple(
        NewContentItem("skill", 29417 + index, f"新增技能 {index}", index, {})
        for index in range(15)
    ) + tuple(
        NewContentItem(
            "skill",
            29413 + index,
            f"修改技能 {index}",
            index,
            {},
            "modified",
        )
        for index in range(4)
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260806",
        weekly_cycle="2026-07-31",
        items=(pet, *skills),
    )

    prompt = _content_prompt(
        snapshot,
        _NewContentMenuLayout(display_categories=("pet", "skill")),
    )

    skill_category = prompt.get_item_by_input("b")
    assert skill_category is not None
    assert skill_category.desc == "15 项新增｜4 项修改"


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
    root_layout = _NewContentMenuLayout(
        display_categories=("pet", "skill", "achievement"),
    )
    layout = _focus_new_content_category(root_layout, "achievement")

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
        _NewContentMenuLayout(
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
    layout = _NewContentMenuLayout(
        display_categories=("achievement",),
        focused_category="achievement",
    )

    prompt = _content_prompt(snapshot, layout)

    assert "a. " not in prompt.build_message()
    assert "b. " not in prompt.build_message()
    assert "1. 深海之泪" in prompt.build_message()
