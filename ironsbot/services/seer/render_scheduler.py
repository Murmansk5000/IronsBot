# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from ironsbot.services.seer.rendering import HtmlTemplateRenderer, TemplatePath


@dataclass(slots=True)
class RenderScheduler:
    """Bound concurrent HTMLKit renders without blocking unrelated work."""

    renderer: HtmlTemplateRenderer
    max_concurrent: int
    _semaphore: asyncio.Semaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    async def render(
        self,
        template_path: TemplatePath,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        async with self._semaphore:
            return await self.renderer(
                template_path,
                template_name,
                templates,
                max_width=max_width,
                allow_refit=allow_refit,
            )
