# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def format_group_label(group_id: int, group_name: str = "") -> str:
    name = group_name.strip()
    return f"{name}（{group_id}）" if name else str(group_id)


async def resolve_group_name(
    bot: Any | None,
    group_id: int,
    *,
    no_cache: bool = False,
) -> str:
    if bot is None:
        return ""
    try:
        info = await bot.get_group_info(group_id=group_id, no_cache=no_cache)
    except Exception as error:  # noqa: BLE001
        logger.debug(
            "failed to resolve OneBot group name: group=%s error=%s",
            group_id,
            error,
        )
        return ""
    return str(
        info.get("group_name", "")
        if isinstance(info, dict)
        else getattr(info, "group_name", "")
    ).strip()
