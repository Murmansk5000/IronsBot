# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.log import logger

from ironsbot.shared.features import get_superuser_ids, groups_for_feature

from .senders import OneBotMessageSender, send_broadcast_message
from .targets import TargetSendSummary

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message

ADMIN_NOTICE_FEATURE = "admin_notice"


@dataclass(frozen=True, slots=True)
class AdminNoticeTargets:
    private_user_ids: list[int]
    group_ids: list[int]

    @property
    def is_empty(self) -> bool:
        return not self.private_user_ids and not self.group_ids


def admin_notice_targets() -> AdminNoticeTargets:
    return AdminNoticeTargets(
        private_user_ids=sorted(get_superuser_ids()),
        group_ids=groups_for_feature(ADMIN_NOTICE_FEATURE),
    )


async def send_admin_notice(
    message: str | Message,
    *,
    subscription_key: str,
    action_name: str,
    bot: OneBotMessageSender | None = None,
    interval_seconds: float = 1.5,
) -> TargetSendSummary:
    targets = admin_notice_targets()
    if targets.is_empty:
        logger.warning(f"{action_name} has no admin notice targets")
        return TargetSendSummary([], [])

    return await send_broadcast_message(
        message,
        private_user_ids=targets.private_user_ids,
        group_ids=targets.group_ids,
        bot=bot,
        action_name=action_name,
        interval_seconds=interval_seconds,
        subscription_key=subscription_key,
    )


__all__ = [
    "ADMIN_NOTICE_FEATURE",
    "AdminNoticeTargets",
    "admin_notice_targets",
    "send_admin_notice",
]
