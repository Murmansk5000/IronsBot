# SPDX-License-Identifier: GPL-3.0-or-later
"""Cache identity and image requirements for new-content rendering."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.services.seer.new_content import (
        NewContentCategory,
        NewContentItem,
        NewContentSnapshot,
    )


def new_content_cache_key(  # noqa: PLR0913
    snapshot: NewContentSnapshot,
    categories: tuple[NewContentCategory, ...],
    focused_category: NewContentCategory | None,
    menu_title: str,
    expanded_categories: frozenset[NewContentCategory],
    auto_expand_max_items: int,
) -> str:
    raw = "|".join(
        (
            snapshot.config_version,
            ",".join(categories),
            focused_category or "root",
            menu_title,
            "expanded=" + ",".join(sorted(expanded_categories)),
            f"auto-expand={auto_expand_max_items}",
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def item_requires_image(item: NewContentItem) -> bool:
    if item.category in {
        "pet",
        "pet_skin",
        "mintmark",
        "suit",
        "equip",
        "mount",
        "autocard_card",
        "autocard_role",
    }:
        return True
    if item.category != "achievement":
        return False
    titles = item.payload.get("titles", [])
    return bool(
        isinstance(titles, list)
        and titles
        and isinstance(titles[0], dict)
        and titles[0].get("id", titles[0].get("title_id", 0))
    )
