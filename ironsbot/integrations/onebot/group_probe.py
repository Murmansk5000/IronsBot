# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import Any

from nonebot.adapters.onebot.v11.exception import ActionFailed

logger = logging.getLogger(__name__)


class OneBotGroupProbe:
    async def can_access(self, bot: Any, *, group_id: int) -> bool:
        try:
            await bot.get_group_info(group_id=group_id, no_cache=True)
        except ActionFailed as error:
            logger.warning(
                "bot cannot access group: group=%s bot_self_id=%s error=%s",
                group_id,
                getattr(bot, "self_id", "unknown"),
                error,
            )
            return False
        return True

    async def has_member(
        self,
        bot: Any,
        *,
        group_id: int,
        user_id: int,
    ) -> bool:
        try:
            await bot.get_group_member_info(
                group_id=group_id,
                user_id=user_id,
                no_cache=True,
            )
        except ActionFailed:
            return False
        return True
