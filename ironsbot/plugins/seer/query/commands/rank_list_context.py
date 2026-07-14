# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nonebot.adapters import Event

RANK_LIST_COMMAND_KEY = "_rank_list_command"
RANK_SCORE_COMMAND_KEY = "_rank_score_command"
RANK_CACHE_BATCH_COMMAND_KEY = "_rank_cache_batch_command"
RANK_PAGE_CACHE_STATUS_COMMAND_KEY = "_rank_page_cache_status_command"
RANK_PAGE_CACHE_REFRESH_COMMAND_KEY = "_rank_page_cache_refresh_command"
RANK_DISPLAY_LIMIT_COMMAND_KEY = "_rank_display_limit_command"


def event_group_id(event: Event) -> int | None:
    group_id = getattr(event, "group_id", None)
    return int(group_id) if group_id is not None else None
