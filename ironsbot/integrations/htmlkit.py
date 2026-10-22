# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from collections.abc import Callable, Coroutine, Mapping
from pathlib import Path
from typing import Any, TypedDict, Unpack

import jinja2

from ironsbot.integrations.litehtml import render_html
from ironsbot.integrations.litehtml.local_resources import local_css, local_image
from ironsbot.services.seer.rendering import TemplatePath

from .project_metadata import current_project_url

HTML_TEMPLATE_RENDERER_SOURCE_PATH = Path(__file__).resolve()


class HtmlResourceCallbacks(TypedDict, total=False):
    img_fetch_fn: Callable[[str], Coroutine[Any, Any, bytes | None]]
    css_fetch_fn: Callable[[str], Coroutine[Any, Any, str | None]]


async def render_html_template(
    template_path: TemplatePath,
    template_name: str,
    templates: Mapping[Any, Any],
    *,
    max_width: int = 500,
    allow_refit: bool = True,
    **resource_callbacks: Unpack[HtmlResourceCallbacks],
) -> bytes:
    context = dict(templates)
    context.setdefault("project_url", current_project_url())
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_path), enable_async=True
    )
    template = await asyncio.to_thread(environment.get_template, template_name)
    base_url = (
        f"file://{Path(template.filename).as_posix()}"
        if template.filename
        else "file:///"
    )
    return await render_html(
        await template.render_async(**context),
        base_url=base_url,
        max_width=max_width,
        allow_refit=allow_refit,
        img_fetch_fn=resource_callbacks.get("img_fetch_fn", local_image),
        css_fetch_fn=resource_callbacks.get("css_fetch_fn", local_css),
    )
