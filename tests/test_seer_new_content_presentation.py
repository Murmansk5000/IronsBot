from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.new_content import NewContentCategory, NewContentItem
from ironsbot.services.seer.rendering.new_content import (
    NewContentMenuItem,
    present_new_content_menu,
    render_new_content_document,
)
from ironsbot.services.seer.rendering.new_content_pool_changes import (
    present_pool_changes,
)

EXPECTED_STANDARD_POOL_CHANGES = 17

if TYPE_CHECKING:
    from collections.abc import Mapping


def _item() -> NewContentMenuItem:
    return NewContentMenuItem(
        code="1",
        name="测试内容",
        description="说明",
        metadata="ID：1",
        side_title="",
        side_description="",
        stats=(),
        stats_layout="inline",
        stats_total="",
        type_name="",
        gender_name="",
        type_icon=None,
        gender_icon=None,
        image_layout="square",
        is_category=False,
        expanded=False,
        image=None,
        skill=None,
        friend_skill=None,
    )


def test_new_content_presenter_freezes_prepared_values() -> None:
    item = _item()
    document = present_new_content_menu(
        "2026-08-05",
        [item],
        {5: "type-icon", "prop": "prop-icon"},
    )

    assert document.content_date == "2026-08-05"
    assert document.items == (item,)
    assert document.templates["items"] == (item,)
    assert document.templates["skill_type_icons"] == {
        5: "type-icon",
        "prop": "prop-icon",
    }


def test_new_content_document_uses_only_the_render_port() -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[str, object],
        **kwargs: object,
    ) -> bytes:
        captured.update(
            template_path=template_path,
            template_name=template_name,
            templates=templates,
            kwargs=kwargs,
        )
        return b"rendered"

    document = present_new_content_menu("2026-08-05", [_item()], {})

    result = asyncio.run(render_new_content_document(render_html, document))

    assert result == b"rendered"
    assert captured["template_name"] == "template.html.j2"
    assert captured["templates"] == document.templates
    assert captured["kwargs"] == {"max_width": 1080, "allow_refit": False}


def _pool_item(
    category: NewContentCategory,
    entity_id: int,
    previous: int | None,
    current: int | None,
) -> NewContentItem:
    return NewContentItem(
        category=category,
        entity_id=entity_id,
        name=f"精灵 {entity_id}",
        sort_value=entity_id,
        payload={"previous_limit": previous, "current_limit": current},
        change_kind="modified",
    )


def test_competitive_pool_preview_keeps_every_transition_in_the_matrix() -> None:
    transitions = (
        *((0, 2) for _ in range(3)),
        *((2, 0) for _ in range(3)),
        *((2, 3) for _ in range(2)),
        *((3, 2) for _ in range(2)),
        *((3, None) for _ in range(3)),
        (None, 2),
        *((None, 3) for _ in range(3)),
    )
    items = tuple(
        _pool_item("peak_pool", index, previous, current)
        for index, (previous, current) in enumerate(transitions, start=1)
    )

    preview = present_pool_changes("peak_pool", items, {})

    assert preview.title == "竞技池变化｜17 只"
    assert preview.headers == ("到限0", "到限2", "到限3", "到不限")
    assert (
        sum(len(pets) for row in preview.matrix_rows for pets in row.cells)
        == EXPECTED_STANDARD_POOL_CHANGES
    )
    assert preview.other_rows == ()


def test_expert_and_master_pool_previews_keep_their_distinct_units() -> None:
    expert = present_pool_changes(
        "peak_expert_pool",
        (
            _pool_item("peak_expert_pool", 1, None, 0),
            _pool_item("peak_expert_pool", 2, 0, None),
        ),
        {},
    )
    master = present_pool_changes(
        "peak_master_pool",
        (_pool_item("peak_master_pool", 3, 4, 6),),
        {},
    )

    assert tuple(row.direction for row in expert.direction_rows) == (
        "不限 → 限0",
        "限0 → 不限",
    )
    assert tuple(row.direction for row in master.direction_rows) == ("4 点 → 6 点",)


def test_new_content_template_renders_pool_change_previews() -> None:
    template = Path(
        "ironsbot/services/seer/rendering/templates/new_content/template.html.j2"
    ).read_text(encoding="utf-8")

    assert "item.pool_preview.matrix_rows" in template
    assert "item.pool_preview.direction_rows" in template
    assert "发送字母查看分类或完整池图片" in template
