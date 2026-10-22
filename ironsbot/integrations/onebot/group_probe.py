# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ironsbot.core.platform import reference_digest
from ironsbot.integrations.onebot.errors import OneBotActionError

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.connections import OneBotConnection

logger = logging.getLogger(__name__)


class OneBotGroupProbe:
    async def can_access(self, bot: OneBotConnection, *, group_id: int) -> bool:
        try:
            await bot.call_api("get_group_info", group_id=group_id, no_cache=True)
        except OneBotActionError as error:
            logger.warning(
                "bot cannot access group: conversation_ref=%s bot_ref=%s error_type=%s",
                reference_digest(str(group_id)),
                reference_digest(bot.self_id),
                type(error).__name__,
            )
            return False
        return True

    async def has_member(
        self,
        bot: OneBotConnection,
        *,
        group_id: int,
        user_id: int,
    ) -> bool:
        try:
            await bot.call_api(
                "get_group_member_info",
                group_id=group_id,
                user_id=user_id,
                no_cache=True,
            )
        except OneBotActionError:
            return False
        return True
