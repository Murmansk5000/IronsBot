# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.log import logger

from .senders import DeliveryResources, OneBotMessageSender, send_broadcast_message
from .targets import TargetSendSummary

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message

    from ironsbot.shared.features import FeatureService

ADMIN_NOTICE_FEATURE = "admin_notice"


@dataclass(frozen=True, slots=True)
class AdminNoticeTargets:
    private_user_ids: list[int]
    group_ids: list[int]

    @property
    def is_empty(self) -> bool:
        return not self.private_user_ids and not self.group_ids


@dataclass(frozen=True, slots=True)
class AdminNoticeService:
    features: FeatureService
    delivery: DeliveryResources

    def targets(self) -> AdminNoticeTargets:
        return AdminNoticeTargets(
            private_user_ids=sorted(self.features.superuser_ids),
            group_ids=self.features.groups_for_feature(ADMIN_NOTICE_FEATURE),
        )

    async def send(
        self,
        message: str | Message,
        *,
        subscription_key: str,
        action_name: str,
        bot: OneBotMessageSender | None = None,
        interval_seconds: float = 1.5,
    ) -> TargetSendSummary:
        targets = self.targets()
        if targets.is_empty:
            logger.warning(f"{action_name} has no admin notice targets")
            return TargetSendSummary([], [])

        return await send_broadcast_message(
            self.delivery,
            message,
            private_user_ids=targets.private_user_ids,
            group_ids=targets.group_ids,
            bot=bot,
            action_name=action_name,
            interval_seconds=interval_seconds,
            subscription_key=subscription_key,
        )
