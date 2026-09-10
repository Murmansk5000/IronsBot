# SPDX-License-Identifier: GPL-3.0-or-later
"""Presentation helpers for modified weekly-content rows."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ironsbot.services.seer.new_content import (
    NewContentItem,
    format_new_content_change_summary,
)

if TYPE_CHECKING:
    from .new_content_skill_details import NewContentItemDetails


def with_change_summary(
    details: NewContentItemDetails,
    item: NewContentItem,
) -> NewContentItemDetails:
    """Attach the compact publisher diff without disturbing normal entries."""

    summary = format_new_content_change_summary(item)
    if not summary:
        return details
    if not details.side_title:
        return replace(
            details,
            side_title="本次修改",
            side_description=summary,
        )
    description = "\n".join(
        value
        for value in (details.description, f"本次修改：{summary}")
        if value
    )
    return replace(details, description=description)
