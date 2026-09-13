# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ironsbot.services.seer.rendering import TemplatePath

from .project_metadata import current_project_url

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

    context = dict(templates)
    context.setdefault("project_url", current_project_url())
    return await template_to_pic(
        template_path,
        template_name,
        context,
        max_width=max_width,
        allow_refit=allow_refit,
    )
