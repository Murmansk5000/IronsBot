# SPDX-License-Identifier: MIT
"""Configuration-driven content categories for Bilibili push delivery."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .parser import dynamic_content

if TYPE_CHECKING:
    from ironsbot.core.bilibili import BiliAccountCategorySubscriptionConfig


def classify_dynamic(
    item: dict[str, object],
    config: BiliAccountCategorySubscriptionConfig | None,
) -> tuple[str, ...]:
    """Return every configured category whose regex matches the dynamic text."""
    if config is None:
        return ()
    content = dynamic_content(item)
    return tuple(
        category
        for category, definition in config.categories.items()
        if any(
            re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
            for pattern in definition.patterns
        )
    )
