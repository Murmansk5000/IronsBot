from typing import Literal

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.seer.query.commands.data_queries import (
    _autocard_sanctuary_effect_detail,
    _content_prompt,
    _item_description,
    _NewContentMenuLayout,
    _skill_detail,
)
from ironsbot.services.seer.new_content import (
    AUTOCARD_NEW_CONTENT_CATEGORIES,
    NewContentItem,
    NewContentSnapshot,
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
            root_categories=AUTOCARD_NEW_CONTENT_CATEGORIES,
            expanded_categories=frozenset(AUTOCARD_NEW_CONTENT_CATEGORIES),
        ),
    )

    assert [item.name for item in prompt.items] == [
        "▼ 新增群星牌",
        "测试卡牌",
        "▼ 新增群星牌角色",
        "测试角色",
        "▼ 新增群星牌圣域",
        "潮涌",
    ]


def test_new_content_root_menu_collapses_categories_by_default() -> None:
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
            root_categories=("pet", "skill"),
            expanded_categories=frozenset(),
        ),
    )

    assert [item.name for item in prompt.items if item.is_visible] == [
        "▶ 新增精灵",
        "▶ 新增技能",
    ]
    assert prompt.get_item_by_input("a1") is not None
    assert prompt.get_item_by_input("b1") is not None
    assert "a1. 超级噗纽" not in prompt.build_message()
    assert "a. ▶ 新增精灵（1 项）" in prompt.build_message()


def test_new_content_root_menu_expands_only_configured_categories() -> None:
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
            root_categories=("pet", "skill"),
            expanded_categories=frozenset(("pet",)),
        ),
    )

    assert [item.name for item in prompt.items if item.is_visible] == [
        "▼ 新增精灵",
        "超级噗纽",
        "▶ 新增技能",
    ]
    assert prompt.get_item_by_input("a1") is not None
    assert prompt.get_item_by_input("b1") is not None


def test_new_content_category_expansion_keeps_root_letter_keys() -> None:
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
        display_categories=("pet", "skill", "achievement"),
        root_categories=("pet", "skill", "achievement"),
        expanded_categories=frozenset(("achievement",)),
    )

    prompt = _content_prompt(snapshot, layout)

    assert "a. ▶ 新增精灵（1 项）" in prompt.build_message()
    assert "b. ▶ 新增技能（1 项）" in prompt.build_message()
    assert "c. ▼ 新增成就（1 项）" in prompt.build_message()
    assert "c1. 深海之泪" in prompt.build_message()


def test_new_content_category_shortcut_reuses_root_letter_key() -> None:
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
        root_categories=("pet", "skill", "achievement"),
        expanded_categories=frozenset(("achievement",)),
    )

    prompt = _content_prompt(snapshot, layout)

    assert "c. ▼ 新增成就（1 项）" in prompt.build_message()
    assert "c1. 深海之泪" in prompt.build_message()
