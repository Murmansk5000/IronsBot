# SPDX-License-Identifier: MIT
"""Configuration-driven content categories for Bilibili push delivery."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .live_preview import LIVE_PREVIEW_CATEGORY, parse_live_preview
from .parser import dynamic_content

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.bilibili import BiliAccountCategorySubscriptionConfig


def classify_dynamic(
    item: Mapping[str, object],
    config: BiliAccountCategorySubscriptionConfig | None,
) -> tuple[str, ...]:
    """Return every configured category whose regex matches the dynamic text."""
    content = dynamic_content(dict(item))
    configured = tuple(
        category
        for category, definition in (config.categories.items() if config else ())
        if any(
            re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
            for pattern in definition.patterns
        )
    )
    if parse_live_preview(dict(item)) is not None:
        return tuple(dict.fromkeys((*configured, LIVE_PREVIEW_CATEGORY)))
    return configured
