# SPDX-License-Identifier: MIT
"""Platform-neutral operational notices for configured administrators."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypeAlias

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import ActorRef, ConversationRef

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService

ADMIN_NOTICE_FEATURE = "admin_notice"
logger = logging.getLogger(__name__)

AdminNoticeRecipient: TypeAlias = ActorRef | ConversationRef


@dataclass(frozen=True, slots=True)
class AdminNoticeSendSummary:
    succeeded: tuple[AdminNoticeRecipient, ...]
    failed: tuple[AdminNoticeRecipient, ...]


class AdminNoticeSender(Protocol):
    """Adapter-owned delivery port preserving each platform's push semantics."""

    async def send_admin_notice(  # noqa: PLR0913
        self,
        message: OutboundMessage,
        *,
        private_actors: tuple[ActorRef, ...],
        group_conversations: tuple[ConversationRef, ...],
        subscription_key: str,
        action_name: str,
        interval_seconds: float,
    ) -> AdminNoticeSendSummary: ...


@dataclass(frozen=True, slots=True)
class AdminNoticeTargets:
    private_actors: tuple[ActorRef, ...]
    group_conversations: tuple[ConversationRef, ...]

    @property
    def is_empty(self) -> bool:
        return not self.private_actors and not self.group_conversations


@dataclass(frozen=True, slots=True)
class AdminNoticeService:
    features: FeatureService
    sender: AdminNoticeSender

    def targets(self) -> AdminNoticeTargets:
        return AdminNoticeTargets(
            private_actors=tuple(self.features.private_admin_notice_actors()),
            group_conversations=tuple(
                self.features.conversations_for_feature(ADMIN_NOTICE_FEATURE)
            ),
        )

    async def send(
        self,
        text: str,
        *,
        subscription_key: str,
        action_name: str,
        interval_seconds: float = 1.5,
    ) -> AdminNoticeSendSummary:
        return await self.send_message(
            OutboundMessage.from_text(text),
            subscription_key=subscription_key,
            action_name=action_name,
            interval_seconds=interval_seconds,
        )

    async def send_message(
        self,
        message: OutboundMessage,
        *,
        subscription_key: str,
        action_name: str,
        interval_seconds: float = 1.5,
    ) -> AdminNoticeSendSummary:
        targets = self.targets()
        if targets.is_empty:
            logger.warning("%s has no admin notice targets", action_name)
            return AdminNoticeSendSummary((), ())

        return await self.sender.send_admin_notice(
            message,
            private_actors=targets.private_actors,
            group_conversations=targets.group_conversations,
            action_name=action_name,
            interval_seconds=interval_seconds,
            subscription_key=subscription_key,
        )

    async def send_private_to_superusers(
        self,
        text: str,
        *,
        subscription_key: str,
        action_name: str,
        interval_seconds: float = 1.5,
    ) -> AdminNoticeSendSummary:
        """Compatibility entrypoint; only explicit private notice opt-ins receive it."""

        private_actors = tuple(self.features.private_admin_notice_actors())
        if not private_actors:
            logger.warning("%s has no superuser private targets", action_name)
            return AdminNoticeSendSummary((), ())

        return await self.sender.send_admin_notice(
            OutboundMessage.from_text(text),
            private_actors=private_actors,
            group_conversations=(),
            action_name=action_name,
            interval_seconds=interval_seconds,
            subscription_key=subscription_key,
        )
