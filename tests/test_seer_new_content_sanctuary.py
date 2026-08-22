import asyncio
from typing import Any, Literal
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.rule import Rule
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
    _empty_new_content_message,
    _focus_new_content_category,
    _is_new_content_input,
    _item_description,
    _NewContentMenuLayout,
    _NewContentServices,
    _render_content_prompt_with_notice,
    _replace_prompt,
    _resolve_new_content_selection,
    _skill_detail,
)
from ironsbot.plugins.seer.query.commands.new_content_routing import (
    install_peak_environment_change_commands,
    visible_new_content_categories,
)
from ironsbot.services.seer.new_content import (
    AUTOCARD_NEW_CONTENT_CATEGORIES,
    PEAK_POOL_NEW_CONTENT_CATEGORIES,
    NewContentCategoryState,
    NewContentItem,
    NewContentSnapshot,
)
from tests.helpers.onebot_events import group_message_event

ROOT_PREVIEW_TOTAL_ITEMS = 9


@pytest.mark.parametrize("message", ("a", "B3", "12", "0"))
def test_new_content_input_accepts_root_preview_keys(message: str) -> None:
    assert _is_new_content_input(group_message_event(message))


@pytest.mark.parametrize("message", ("a0", "ab", "00", "-1"))
def test_new_content_input_rejects_invalid_root_preview_keys(message: str) -> None:
    assert not _is_new_content_input(group_message_event(message))


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

    with pytest.raises(ValidationError, match="expanded_categories"):
        SeerConfig.model_validate(
            {"new_content": {"expanded_categories": ["peak_pool"]}}
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


class _RecordingMatcher:
    def __init__(self, state: dict[str, object] | None = None) -> None:
        self.state = {} if state is None else state
        self.sent: list[object] = []

    async def send(self, message: object) -> dict[str, int]:
        self.sent.append(message)
        return {"message_id": len(self.sent)}

    async def finish(self, message: object) -> None:
        raise AssertionError(message)


class _RegisteredMatcher:
    def __init__(self) -> None:
        self.handler: Any | None = None

    def append_handler(self, handler: Any) -> None:
        self.handler = handler


class _RegistrationGroup:
    def __init__(self) -> None:
        self.features = object()
        self.matcher = _RegisteredMatcher()
        self.commands: tuple[str, ...] = ()

    def matcher_priority(self, _plugin_id: str) -> int:
        return 1

    def on_fullmatch(
        self,
        commands: tuple[str, ...],
        **_kwargs: Any,
    ) -> _RegisteredMatcher:
        self.commands = commands
        return self.matcher


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


def test_peak_environment_changes_root_keeps_the_a_b_menu() -> None:
    standard = NewContentItem(
        "peak_pool",
        1,
        "竞技池精灵",
        1,
        {"previous_limit": 0, "current_limit": 2},
        "modified",
    )
    expert = NewContentItem(
        "peak_expert_pool",
        2,
        "专家池精灵",
        2,
        {"previous_limit": None, "current_limit": 0},
        "modified",
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260814",
        weekly_cycle="2026-08-14",
        items=(standard, expert),
    )
    prompt = _content_prompt(
        snapshot,
        _NewContentMenuLayout(
            display_categories=("peak_pool", "peak_expert_pool"),
            root_title="巅峰环境变化",
        ),
    )
    assert prompt.title == "🆕【巅峰环境变化】输入编号查看详情：\n"
    assert [item.value.category for item in prompt.items] == [
        "peak_pool",
        "peak_expert_pool",
    ]
    assert prompt.get_item_by_input("a") is not None
    assert prompt.get_item_by_input("b") is not None


def test_peak_environment_without_changes_suggests_current_pool_queries() -> None:
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260821",
        weekly_cycle="2026-08-21",
        items=(),
    )

    assert _empty_new_content_message(
        snapshot,
        PEAK_POOL_NEW_CONTENT_CATEGORIES,
        all_categories_comparable=True,
    ) == "本周竞技池和专家池均未变化。\n可发送“竞技池”或“专家池”查看当前池。"


def test_peak_environment_without_complete_baseline_keeps_unavailable_message() -> None:
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260821",
        weekly_cycle="2026-08-21",
        items=(),
        category_states=(
            NewContentCategoryState(
                category="peak_pool",
                comparison_ready=True,
                reason="ready",
            ),
            NewContentCategoryState(
                category="peak_expert_pool",
                comparison_ready=False,
                reason="first_observation",
            ),
        ),
    )

    message = _empty_new_content_message(
        snapshot,
        PEAK_POOL_NEW_CONTENT_CATEGORIES,
    )

    assert "均未变化" not in message
    assert "已开始记录" in message


def test_peak_environment_change_command_starts_the_shared_menu() -> None:
    group = _RegistrationGroup()
    start_menu = AsyncMock()
    service = object()

    install_peak_environment_change_commands(
        group,  # type: ignore[arg-type]
        service,  # type: ignore[arg-type]
        Rule(),
        start_menu,
    )

    assert group.matcher.handler is not None
    matcher = _RecordingMatcher()
    state: dict[str, object] = {}
    event = group_message_event(user_id=123)
    asyncio.run(
        group.matcher.handler(
            matcher,
            state,
            event,
        )
    )
    start_menu.assert_awaited_once_with(
        service,
        ("peak_pool", "peak_expert_pool"),
        group,
        matcher,
        state,
        event,
        root_title="巅峰环境变化",
    )


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
                peak=object(),
                references=object(),
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
        "▼ 新增群星牌卡牌",
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
            auto_expand_max_items=5,
        ),
    )

    assert [item.name for item in prompt.items if item.is_visible] == [
        "▼ 新增精灵",
        "超级噗纽",
        "▶ 新增技能",
    ]
    first_item = prompt.get_item_by_input("a1")
    assert first_item is not None and first_item.value.item == pet
    assert prompt.get_item_by_input("b1") is None
    assert "a1. 超级噗纽" in prompt.build_message()
    assert "a. ▼ 新增精灵（1 项新增）" in prompt.build_message()


def test_new_content_root_menu_keeps_modified_items_folded() -> None:
    changed_pet = NewContentItem(
        category="pet",
        entity_id=4930,
        name="修改精灵",
        sort_value=4930,
        payload={},
        change_kind="modified",
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260814",
        weekly_cycle="2026-08-14",
        items=(changed_pet,),
    )

    root = _content_prompt(
        snapshot,
        _NewContentMenuLayout(
            display_categories=("pet",),
            expanded_categories=frozenset({"pet"}),
            auto_expand_max_items=5,
        ),
    )
    focused = _content_prompt(
        snapshot,
        _focus_new_content_category(
            _NewContentMenuLayout(display_categories=("pet",)), "pet"
        ),
    )

    assert "a. ▶ 新增精灵（1 项修改）" in root.build_message()
    assert root.get_item_by_input("a1") is None
    assert focused.get_item_by_input("1") is not None


def test_new_content_root_menu_keeps_unconfigured_categories_folded() -> None:
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
    skill_category = prompt.get_item_by_input("b")
    assert prompt.get_item_by_input("a1") is None
    assert all(prompt.get_item_by_input(f"b{index}") is None for index in range(1, 7))
    assert skill_category is not None and skill_category.value.category == "skill"


def test_new_content_root_menu_does_not_auto_expand_short_categories() -> None:
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

    assert "a. ▶ 新增精灵（1 项新增）" in prompt.build_message()
    assert "a1. 超级噗纽" not in prompt.build_message()


def test_new_content_root_preview_caps_items_but_focused_menu_keeps_all() -> None:
    mintmarks = tuple(
        NewContentItem("mintmark", index, f"刻印 {index}", index, {})
        for index in range(1, ROOT_PREVIEW_TOTAL_ITEMS + 1)
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260814",
        weekly_cycle="2026-08-14",
        items=mintmarks,
    )
    root_layout = _NewContentMenuLayout(
        display_categories=("mintmark",),
        expanded_categories=frozenset({"mintmark"}),
        auto_expand_max_items=5,
    )

    root_prompt = _content_prompt(snapshot, root_layout)
    focused_prompt = _content_prompt(
        snapshot,
        _focus_new_content_category(root_layout, "mintmark"),
    )

    assert [item.key for item in root_prompt.items if item.is_visible] == [
        "a",
        "a1",
        "a2",
        "a3",
        "a4",
        "a5",
    ]
    assert root_prompt.get_item_by_input("a6") is None
    assert len(focused_prompt.items) == ROOT_PREVIEW_TOTAL_ITEMS
    assert focused_prompt.get_item_by_input(str(ROOT_PREVIEW_TOTAL_ITEMS)) is not None


def test_pool_categories_without_changes_are_hidden() -> None:
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260814",
        weekly_cycle="2026-08-14",
        items=(NewContentItem("pet", 1, "新增精灵", 1, {}),),
    )

    assert visible_new_content_categories(
        snapshot,
        ("pet", "peak_pool", "peak_expert_pool"),
    ) == ("pet",)


@pytest.mark.asyncio
async def test_pool_category_letters_send_existing_full_pool_images(
    monkeypatch: Any,
) -> None:
    standard = NewContentItem(
        "peak_pool",
        1,
        "标准池精灵",
        1,
        {"previous_limit": 0, "current_limit": 2},
        "modified",
    )
    expert = NewContentItem(
        "peak_expert_pool",
        2,
        "专家池精灵",
        2,
        {"previous_limit": None, "current_limit": 0},
        "modified",
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260814",
        weekly_cycle="2026-08-14",
        items=(standard, expert),
    )
    prompt = _content_prompt(
        snapshot,
        _NewContentMenuLayout(
            display_categories=("peak_pool", "peak_expert_pool")
        ),
    )
    send_pool = AsyncMock()
    monkeypatch.setattr(
        "ironsbot.plugins.seer.query.commands.data_queries.send_peak_pool",
        send_pool,
    )
    services = _NewContentServices(
        pet=object(),
        mintmark=object(),
        equipment=object(),
        autocard=object(),
        peak=object(),
        references=object(),
        menu_renderer=object(),
    )
    matcher = _RecordingMatcher(
        {
            NEW_CONTENT_SNAPSHOT_KEY: snapshot,
            NEW_CONTENT_SERVICES_KEY: services,
        }
    )
    standard_choice = prompt.get_item_by_input("a")
    expert_choice = prompt.get_item_by_input("b")
    assert standard_choice is not None and expert_choice is not None

    await _resolve_new_content_selection(
        standard_choice,
        matcher,  # type: ignore[arg-type]
        group_message_event(),
    )
    await _resolve_new_content_selection(
        expert_choice,
        matcher,  # type: ignore[arg-type]
        group_message_event(),
    )

    assert [item.name for item in prompt.items] == [
        "↗ 竞技池变化",
        "↗ 专家池变化",
    ]
    assert all(item.value.item is None for item in prompt.items)
    assert send_pool.await_args_list[0].kwargs == {"expert": False}
    assert send_pool.await_args_list[1].kwargs == {"expert": True}


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


def test_focused_new_content_menu_keeps_root_category_shortcuts_hidden() -> None:
    skill = NewContentItem(
        category="skill",
        entity_id=38474,
        name="金属缠绕",
        sort_value=38474,
        payload={},
    )
    autocard = NewContentItem(
        category="autocard_card",
        entity_id=98,
        name="测试卡牌",
        sort_value=98,
        payload={},
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260821",
        weekly_cycle="2026-08-21",
        items=(skill, autocard),
    )

    prompt = _content_prompt(
        snapshot,
        _NewContentMenuLayout(
            display_categories=("skill", "autocard_card"),
            focused_category="skill",
        ),
    )

    assert "b. 新增群星牌卡牌" not in prompt.build_message()
    shortcut = prompt.get_item_by_input("b")
    assert shortcut is not None
    assert shortcut.value.kind == "category"
    assert shortcut.value.category == "autocard_card"
