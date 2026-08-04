# SPDX-License-Identifier: GPL-3.0-or-later
"""Render an already prepared pet information document."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import HtmlTemplateRenderer, TemplatePath
    from .pet_info_models import PetInfoRenderDocument


async def render_pet_info_document(
    render_html: HtmlTemplateRenderer,
    template_path: TemplatePath,
    document: PetInfoRenderDocument,
) -> bytes:
    """Invoke the HTML port without reading data, assets, or local paths."""
    return await render_html(
        template_path=template_path,
        template_name=document.template_name,
        templates=document.templates,
        max_width=1200,
        allow_refit=False,
    )
