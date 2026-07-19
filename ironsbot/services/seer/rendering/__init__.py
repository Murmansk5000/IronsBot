# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Mapping, Sequence
from os import PathLike
from typing import Any, Protocol, TypeAlias

TemplatePath: TypeAlias = (
    str | PathLike[str] | Sequence[str | PathLike[str]]
)


class HtmlTemplateRenderer(Protocol):
    async def __call__(
        self,
        template_path: TemplatePath,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes: ...
