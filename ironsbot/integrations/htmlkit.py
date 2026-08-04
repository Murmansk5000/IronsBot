# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ironsbot.services.seer.rendering import TemplatePath

HTML_TEMPLATE_RENDERER_SOURCE_PATH = Path(__file__).resolve()


async def render_html_template(
    template_path: TemplatePath,
    template_name: str,
    templates: Mapping[Any, Any],
    *,
    max_width: int = 500,
    allow_refit: bool = True,
) -> bytes:
    from nonebot_plugin_htmlkit import template_to_pic

    return await template_to_pic(
        template_path,
        template_name,
        templates,
        max_width=max_width,
        allow_refit=allow_refit,
    )
