# SPDX-License-Identifier: GPL-3.0-or-later
"""Plain visible text for weekly presentation, never for ordinary detail cards."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING

from .rendering.analyze_description import annotate_soulmark_boss_effects

if TYPE_CHECKING:
    from .rendering.custom_pet_models import SkillDict

_SPRITE = re.compile(r"\[sprite\s*name=(\w+)\]")
_COLOR = re.compile(r"\[(?:color=[^\[\]\r\n]*|/color)\]")


def plain_weekly_text(value: str, *, soulmark: bool = False) -> str:
    """Remove game controls, preserving all other characters and paragraph text."""
    value = _SPRITE.sub(r"[sprite name=\1]", value)
    if soulmark:
        value = re.sub(r"(?<=[^|\r\n])(?=\[sprite name=)", "|", value)
        value = value.replace("\r\n", "|").replace("\n", "|")
        value = annotate_soulmark_boss_effects(value)
    return _COLOR.sub("", _SPRITE.sub("", value)).replace("|", "\n")


class _VisibleHtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "br":
            self.parts.append("\n")


def plain_weekly_skill(skill: SkillDict | None) -> SkillDict | None:
    """Unwrap only the description HTML already produced by the safe formatter."""
    if skill is None:
        return None

    def visible(value: str | None) -> str | None:
        if value is None:
            return None
        parser = _VisibleHtmlText()
        parser.feed(value)
        parser.close()
        return plain_weekly_text("".join(parser.parts))

    result = skill.copy()
    result["info"] = visible(skill["info"])
    result["hide_effect_desc"] = visible(skill["hide_effect_desc"])
    result["effects"] = [
        {**effect, "info": visible(str(effect.get("info", ""))) or ""}
        for effect in skill["effects"]
    ]
    return result
