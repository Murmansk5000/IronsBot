# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.core.messaging import TargetSendSummary

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService

    from .delivery import MessageDelivery

ADMIN_NOTICE_FEATURE = "admin_notice"
logger = logging.getLogger(__name__)


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
    delivery: MessageDelivery

    def targets(self) -> AdminNoticeTargets:
        return AdminNoticeTargets(
            private_user_ids=sorted(self.features.superuser_ids),
            group_ids=self.features.groups_for_feature(ADMIN_NOTICE_FEATURE),
        )

    async def send(
        self,
        message: Any,
        *,
        subscription_key: str,
        action_name: str,
        bot: Any | None = None,
        interval_seconds: float = 1.5,
    ) -> TargetSendSummary:
        targets = self.targets()
        if targets.is_empty:
            logger.warning(f"{action_name} has no admin notice targets")
            return TargetSendSummary([], [])

        return await self.delivery.broadcast(
            message,
            private_user_ids=targets.private_user_ids,
            group_ids=targets.group_ids,
            bot=bot,
            action_name=action_name,
            interval_seconds=interval_seconds,
            subscription_key=subscription_key,
        )

    async def send_private_to_superusers(
        self,
        message: Any,
        *,
        subscription_key: str,
        action_name: str,
        bot: Any | None = None,
        interval_seconds: float = 1.5,
    ) -> TargetSendSummary:
        """Send an operational notice only to configured superusers in private."""

        private_user_ids = sorted(self.features.superuser_ids)
        if not private_user_ids:
            logger.warning(f"{action_name} has no superuser private targets")
            return TargetSendSummary([], [])

        return await self.delivery.broadcast(
            message,
            private_user_ids=private_user_ids,
            group_ids=(),
            bot=bot,
            action_name=action_name,
            interval_seconds=interval_seconds,
            subscription_key=subscription_key,
        )
