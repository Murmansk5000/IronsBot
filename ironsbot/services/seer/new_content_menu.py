# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-neutral planning for release content selection menus."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from .new_content import (
    AUTOCARD_NEW_CONTENT_CATEGORIES,
    CATEGORY_NAMES,
    DEFAULT_NEW_CONTENT_AUTO_EXPAND_MAX_ITEMS,
    NewContentCategory,
    NewContentItem,
    NewContentSnapshot,
    format_new_content_item_description,
    is_new_content_category_auto_expanded,
    new_content_category_preview_items,
    new_content_category_unavailable_message,
)


@dataclass(frozen=True, slots=True)
class NewContentAction:
    kind: Literal["category", "item"]
    category: NewContentCategory
    item: NewContentItem | None = None


@dataclass(frozen=True, slots=True)
class NewContentMenuLayout:
    display_categories: tuple[NewContentCategory, ...]
    focused_category: NewContentCategory | None = None
    expanded_categories: frozenset[NewContentCategory] = frozenset()
    preview_max_items: int = DEFAULT_NEW_CONTENT_AUTO_EXPAND_MAX_ITEMS


@dataclass(frozen=True, slots=True)
class NewContentChoice:
    name: str
    description: str
    action: NewContentAction


@dataclass(frozen=True, slots=True)
class NewContentMenu:
    title: str
    choices: tuple[NewContentChoice, ...]


def plan_new_content_menu(
    snapshot: NewContentSnapshot,
    available: tuple[NewContentCategory, ...],
    requested: tuple[NewContentCategory, ...] | None = None,
    *,
    expanded_categories: frozenset[NewContentCategory] = frozenset(),
    preview_max_items: int = DEFAULT_NEW_CONTENT_AUTO_EXPAND_MAX_ITEMS,
) -> NewContentMenuLayout | str:
    """Return a visible layout or the reason no selection can be offered."""

    if requested is not None and not set(requested).issubset(available):
        return "当前群未开放此新增内容分类。"
    categories = available if requested is None else requested
    comparable: tuple[NewContentCategory, ...] = tuple(
        category for category in categories if snapshot.is_category_comparable(category)
    )
    if requested is not None and not comparable:
        return new_content_category_unavailable_message(snapshot, requested)
    visible: tuple[NewContentCategory, ...] = tuple(
        category for category in comparable if snapshot.items_for(category)
    )
    if requested is not None and not visible:
        return _empty_new_content_message(snapshot, requested)
    if not visible:
        return "本周暂未检测到可验证的新增或修改内容。"
    return NewContentMenuLayout(
        display_categories=visible,
        focused_category=(
            requested[0] if requested is not None and len(requested) == 1 else None
        ),
        expanded_categories=frozenset(
            category
            for category in visible
            if new_content_category_preview_items(
                snapshot,
                category,
                preview_max_items,
            )
            and (
                category in expanded_categories
                or is_new_content_category_auto_expanded(
                    snapshot, category, preview_max_items
                )
            )
        ),
        preview_max_items=preview_max_items,
    )


def focus_new_content_category(
    layout: NewContentMenuLayout, category: NewContentCategory
) -> NewContentMenuLayout:
    if category not in layout.display_categories:
        msg = "new-content category is not available in this menu"
        raise ValueError(msg)
    return replace(layout, display_categories=(category,), focused_category=category)


def build_new_content_menu(
    snapshot: NewContentSnapshot, layout: NewContentMenuLayout
) -> NewContentMenu:
    if layout.focused_category is not None:
        category = layout.focused_category
        if category not in layout.display_categories:
            msg = "focused new-content category is not visible"
            raise ValueError(msg)
        return NewContentMenu(
            title=f"🆕【{CATEGORY_NAMES[category]}】输入编号查看详情：",
            choices=tuple(_item_choice(item) for item in snapshot.items_for(category)),
        )
    choices: list[NewContentChoice] = []
    for category in layout.display_categories:
        items = snapshot.items_for(category)
        choices.append(
            NewContentChoice(
                name=f"▶ {CATEGORY_NAMES[category]}",
                description=f"{len(items)} 项",
                action=NewContentAction("category", category),
            )
        )
        if category in layout.expanded_categories:
            choices.extend(
                _item_choice(item)
                for item in new_content_category_preview_items(
                    snapshot,
                    category,
                    layout.preview_max_items,
                )
            )
    return NewContentMenu(
        title="🆕【新增内容】输入编号查看详情：", choices=tuple(choices)
    )


def _item_choice(item: NewContentItem) -> NewContentChoice:
    return NewContentChoice(
        name=item.name,
        description=format_new_content_item_description(item),
        action=NewContentAction("item", item.category, item),
    )


def _empty_new_content_message(
    snapshot: NewContentSnapshot, categories: tuple[NewContentCategory, ...]
) -> str:
    name = (
        "新增群星牌"
        if categories == AUTOCARD_NEW_CONTENT_CATEGORIES
        else CATEGORY_NAMES[categories[0]]
    )
    first_observations: tuple[NewContentCategory, ...] = tuple(
        category
        for category in categories
        if snapshot.category_state(category).reason == "first_observation"
    )
    if first_observations:
        notice = new_content_category_unavailable_message(snapshot, first_observations)
        return f"本周暂无{name}。{notice}"
    return f"本周暂无{name}。"
