from __future__ import annotations

from dataclasses import replace

import pytest

from ironsbot.integrations.seer_data.new_content_snapshot import _fallback_details
from ironsbot.services.seer.new_content import (
    AUTOCARD_NEW_CONTENT_CATEGORIES,
    NEW_CONTENT_CATEGORIES,
    NewContentCategory,
    NewContentCategoryState,
    NewContentItem,
    NewContentSnapshot,
)
from ironsbot.services.seer.new_content_menu import (
    NewContentMenuLayout,
    build_new_content_menu,
    focus_new_content_category,
    plan_new_content_menu,
)


def _snapshot(*categories: NewContentCategory) -> NewContentSnapshot:
    return NewContentSnapshot(
        baseline_established=True,
        config_version="20260904",
        weekly_cycle="2026-09-04",
        items=tuple(
            NewContentItem(
                category,
                index,
                f"Item {index}",
                index,
                {"pets": [{"id": 999, "name": "Existing pet"}]}
                if category == "skill"
                else {},
            )
            for index, category in enumerate(categories, start=1)
        ),
        category_states=tuple(
            NewContentCategoryState(
                category, comparison_ready=True, reason="comparable"
            )
            for category in NEW_CONTENT_CATEGORIES
        ),
    )


def test_plan_filters_unavailable_and_empty_categories() -> None:
    snapshot = _snapshot("pet", "skill")
    layout = plan_new_content_menu(snapshot, ("skill", "achievement"))

    assert isinstance(layout, NewContentMenuLayout)
    assert layout.display_categories == ("skill",)
    assert layout.focused_category is None
    menu = build_new_content_menu(snapshot, layout)
    assert [choice.key for choice in menu.choices] == ["a", "a1"]
    assert menu.choices[1].action.item == snapshot.items[1]
    with pytest.raises(ValueError, match="not available"):
        focus_new_content_category(layout, "pet")


def test_chip_modifications_preview_five_and_join_autocard_menu() -> None:
    chip_count = 9
    preview_count = 5
    assert "autocard_chip" in AUTOCARD_NEW_CONTENT_CATEGORIES
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260924175611",
        weekly_cycle="2026-09-25",
        items=tuple(
            NewContentItem(
                "autocard_chip", index, f"芯片 {index}", index,
                {
                    "rarity": 1,
                    "description": "新效果",
                    "previous_description": "旧效果",
                },
                "modified",
            )
            for index in range(1, chip_count + 1)
        ),
        category_states=(
            NewContentCategoryState(
                "autocard_chip", comparison_ready=True, reason="ready"
            ),
        ),
    )
    layout = plan_new_content_menu(snapshot, ("autocard_chip",))
    assert isinstance(layout, NewContentMenuLayout)
    assert "autocard_chip" in layout.expanded_categories
    menu = build_new_content_menu(snapshot, layout)
    assert len(menu.choices) == preview_count + 1
    focused = build_new_content_menu(
        snapshot, focus_new_content_category(layout, "autocard_chip")
    )
    assert len(focused.choices) == chip_count


def test_chip_rarity_change_does_not_claim_effect_changed() -> None:
    item = NewContentItem(
        "autocard_chip", 84, "星能震荡", 84,
        {
            "category": "战斗输出类",
            "description": "每个战斗阶段开始时造成伤害",
            "previous_description": "每个战斗阶段开始时造成伤害",
            "change_summary": ["rarity：1 → 2"],
        },
        "modified",
    )
    details = _fallback_details(item)
    assert "档位：普通 → 稀有" in details.side_description
    assert "原效果" not in details.side_description
    assert "效果：每个战斗阶段开始时造成伤害" in details.side_description


def test_explicit_denied_category_returns_notice() -> None:
    assert plan_new_content_menu(_snapshot("pet"), ("skill",), ("pet",)) == (
        "当前群未开放此新增内容分类。"
    )


def test_stale_week_notice_preserves_permission_denial() -> None:
    snapshot = replace(
        _snapshot("pet"),
        is_current_week=False,
        source_weekly_cycle="2026-09-04",
        items=(),
        category_states=(),
    )
    assert plan_new_content_menu(snapshot, ("pet",)) == (
        "当前数据版本仍为 2026-09-04 周期，"
        "本周暂未获得可验证的新增或修改内容。"
    )
    assert plan_new_content_menu(snapshot, ("skill",), ("pet",)) == (
        "当前群未开放此新增内容分类。"
    )


def test_focus_preserves_item_order_and_uses_numeric_adapter_keys() -> None:
    snapshot = _snapshot("pet", "skill", "pet")
    layout = plan_new_content_menu(snapshot, ("pet", "skill"))
    assert isinstance(layout, NewContentMenuLayout)

    focused = focus_new_content_category(layout, "pet")
    menu = build_new_content_menu(snapshot, focused)
    assert focused.display_categories == ("pet",)
    assert focused.root_categories == ("pet", "skill")
    assert [choice.action.item for choice in menu.choices if choice.is_visible] == [
        snapshot.items[0],
        snapshot.items[2],
    ]
    assert [choice.key for choice in menu.choices] == [None, None, "b"]
    assert not menu.choices[-1].is_visible
    switched = focus_new_content_category(focused, "skill")
    assert switched.root_categories == focused.root_categories
    switched_keys = [
        choice.key for choice in build_new_content_menu(snapshot, switched).choices
    ]
    assert switched_keys == [
        None,
        "a",
    ]


@pytest.mark.parametrize(("count", "expanded"), [(5, True), (6, False)])
def test_auto_expansion_has_one_shared_threshold(count: int, *, expanded: bool) -> None:
    categories: tuple[NewContentCategory, ...] = ("pet",) * count
    snapshot = _snapshot(*categories)
    layout = plan_new_content_menu(snapshot, ("pet",))
    assert isinstance(layout, NewContentMenuLayout)
    assert ("pet" in layout.expanded_categories) is expanded
    assert len(build_new_content_menu(snapshot, layout).choices) == (
        count + 1 if expanded else 1
    )


def test_explicit_preview_is_bounded_and_keeps_corrections_folded() -> None:
    items = (
        *(
            NewContentItem("pet", index, f"Pet {index}", index, {})
            for index in range(1, 7)
        ),
        NewContentItem("pet", 7, "Correction", 7, {}, "modified"),
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260911",
        weekly_cycle="2026-09-11",
        items=items,
        category_states=(
            NewContentCategoryState("pet", comparison_ready=True, reason="comparable"),
        ),
    )

    layout = plan_new_content_menu(
        snapshot,
        ("pet",),
        expanded_categories=frozenset({"pet"}),
        preview_max_items=2,
    )

    assert isinstance(layout, NewContentMenuLayout)
    assert layout.expanded_categories == frozenset({"pet"})
    menu = build_new_content_menu(snapshot, layout)
    assert [choice.action.item for choice in menu.choices[1:]] == list(items[:2])


def test_incomparable_category_is_not_reported_as_no_changes() -> None:
    snapshot = replace(
        _snapshot("pet"),
        category_states=(
            NewContentCategoryState(
                "pet", comparison_ready=False, reason="first_observation"
            ),
        ),
    )
    result = plan_new_content_menu(snapshot, ("pet",), ("pet",))
    assert isinstance(result, str)
    assert "已开始记录" in result
    assert "本周暂无" not in result
    assert plan_new_content_menu(snapshot, ("pet",)) == (
        "本周暂未检测到可验证的新增或修改内容。"
    )


def test_empty_comparable_category_has_explicit_notice() -> None:
    assert (
        plan_new_content_menu(_snapshot(), ("skill",), ("skill",))
        == "本周暂无新增技能。"
    )


def test_focused_layout_cannot_expose_a_hidden_category() -> None:
    layout = NewContentMenuLayout(("skill",), focused_category="pet")
    with pytest.raises(ValueError, match="not visible"):
        build_new_content_menu(_snapshot("pet", "skill"), layout)
