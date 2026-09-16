# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import Any

from nonebot.adapters.onebot.v11.exception import ActionFailed

from ironsbot.core.platform import reference_digest

logger = logging.getLogger(__name__)


class OneBotGroupProbe:
    async def can_access(self, bot: Any, *, group_id: int) -> bool:
        try:
            await bot.get_group_info(group_id=group_id, no_cache=True)
        except ActionFailed as error:
            logger.warning(
                "bot cannot access group: conversation_ref=%s bot_ref=%s "
                "error_type=%s",
                reference_digest(str(group_id)),
                reference_digest(str(getattr(bot, "self_id", "unknown"))),
                type(error).__name__,
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
