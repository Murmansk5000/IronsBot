from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.rendering.new_content import (
    NewContentMenuItem,
    present_new_content_menu,
    render_new_content_document,
)

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
