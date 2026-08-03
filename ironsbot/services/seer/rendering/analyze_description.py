# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared rendering for official Analyze descriptions."""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING

from ironsbot.services.ai.analysis_parser import AnalyzeDescParser

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_ANALYZE_DESC_STYLES: dict[str, Callable[..., str]] = {
    "#f35555": lambda text: f'<b style="color:#f35555">{text}</b>',
    "#57c975": lambda text: f'<b style="color:#57c975">{text}</b>',
    "#52a5f2": lambda text: f'<b style="color:#52a5f2">{text}</b>',
    "#64F9FA": lambda text: f'<b style="color:#64F9FA">{text}</b>',
    "#FFF779": lambda text: f'<b style="color:#FFF779">{text}</b>',
}


def format_analyze_description(
    value: str | None,
    effect_colors: Mapping[str, str] | None = None,
) -> str:
    """Render supported official color tags and omit sprite control tags."""

    resolved_colors = effect_colors or {}
    names = tuple(sorted(resolved_colors, key=len, reverse=True))
    pattern = (
        re.compile("|".join(re.escape(name) for name in names)) if names else None
    )
    lines: list[str] = []
    for line in AnalyzeDescParser(value or "").lines:
        parts: list[str] = []
        for segment in line.segments:
            rendered = html.escape(segment.text)
            if segment.colors:
                seen: set[str] = set()
                for color in reversed(segment.colors):
                    if color not in seen and (
                        styler := _ANALYZE_DESC_STYLES.get(color)
                    ):
                        rendered = styler(rendered)
                        seen.add(color)
            elif pattern is not None:
                rendered = pattern.sub(
                    lambda match: (
                        f'<b style="color:{resolved_colors[match.group(0)]}">'
                        f"{html.escape(match.group(0))}</b>"
                    ),
                    rendered,
                )
            parts.append(rendered)
        lines.append("".join(parts))
    return "<br>".join(lines)


def format_plain_analyze_description(
    value: str | None,
    effect_colors: Mapping[str, str] | None = None,
) -> str | None:
    if value is None:
        return None
    return format_analyze_description(value, effect_colors)
