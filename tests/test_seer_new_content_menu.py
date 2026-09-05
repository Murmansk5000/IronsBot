from __future__ import annotations

from dataclasses import replace

import pytest

from ironsbot.services.seer.new_content import (
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
            NewContentItem(category, index, f"Item {index}", index, {})
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


def test_explicit_denied_category_returns_notice() -> None:
    assert plan_new_content_menu(_snapshot("pet"), ("skill",), ("pet",)) == (
        "当前群未开放此新增内容分类。"
    )


def test_focus_preserves_item_order_and_uses_numeric_adapter_keys() -> None:
    snapshot = _snapshot("pet", "skill", "pet")
    layout = plan_new_content_menu(snapshot, ("pet", "skill"))
    assert isinstance(layout, NewContentMenuLayout)

    focused = focus_new_content_category(layout, "pet")
    menu = build_new_content_menu(snapshot, focused)
    assert focused.display_categories == ("pet",)
    assert [choice.action.item for choice in menu.choices] == [
        snapshot.items[0],
        snapshot.items[2],
    ]
    assert all(choice.key is None for choice in menu.choices)


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
