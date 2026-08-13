# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure documents and HTML rendering for the weekly new-content menu."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ironsbot.services.seer.render_paths import (
    NEW_CONTENT_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from . import HtmlTemplateRenderer
    from .custom_pet_models import SkillDict


@dataclass(frozen=True, slots=True)
class NewContentMenuItem:
    """A fully prepared visual row for the weekly new-content menu."""

    code: str
    name: str
    description: str
    metadata: str
    side_title: str
    side_description: str
    stats: tuple[tuple[str, str], ...]
    stats_layout: str
    stats_total: str
    type_name: str
    gender_name: str
    type_icon: str | None
    gender_icon: str | None
    image_layout: str
    is_category: bool
    expanded: bool
    image: str | None
    skill: SkillDict | None
    friend_skill: SkillDict | None
    image_notice: str = ""
    entity_key: tuple[str, int] | None = None


@dataclass(frozen=True, slots=True)
class NewContentMenuDocument:
    """Immutable template input with no repository or image-source knowledge."""

    content_date: str
    items: tuple[NewContentMenuItem, ...]
    skill_type_icons: tuple[tuple[int | str, str], ...]
    menu_title: str = "新增内容"

    @property
    def templates(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "content_date": self.content_date,
                "menu_title": self.menu_title,
                "items": self.items,
                "skill_type_icons": MappingProxyType(dict(self.skill_type_icons)),
            }
        )


def present_new_content_menu(
    content_date: str,
    items: Sequence[NewContentMenuItem],
    skill_type_icons: Mapping[int | str, str],
    menu_title: str = "新增内容",
) -> NewContentMenuDocument:
    """Freeze prepared menu values into a render-ready document."""
    return NewContentMenuDocument(
        content_date=content_date,
        items=tuple(items),
        skill_type_icons=tuple(skill_type_icons.items()),
        menu_title=menu_title,
    )


async def render_new_content_document(
    render_html: HtmlTemplateRenderer,
    document: NewContentMenuDocument,
) -> bytes:
    """Render a prepared document through the shared native render port."""
    return await render_html(
        template_path=[NEW_CONTENT_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        template_name="template.html.j2",
        templates=document.templates,
        max_width=1080,
        allow_refit=False,
    )
