# SPDX-License-Identifier: MIT
"""OneBot adapters for the platform-neutral team-audit service."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.services.team.audit import TEAM_AUDIT_FEATURE

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService
    from ironsbot.integrations.onebot.group_probe import OneBotGroupProbe
    from ironsbot.integrations.onebot.router import BotRouter

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OneBotTeamAuditPolicy:
    """Adapt configured OneBot group features to the core audit policy."""

    features: FeatureService

    def enabled_for(self, conversation: ConversationRef) -> bool:
        group_id = _onebot_group_id(conversation)
        return group_id is not None and self.features.group_has_feature(
            group_id,
            TEAM_AUDIT_FEATURE,
        )


@dataclass(frozen=True, slots=True)
class OneBotTeamAuditMembershipProbe:
    """Check OneBot group access and member presence at the integration edge."""

    router: BotRouter
    probe: OneBotGroupProbe

    async def can_access(self, conversation: ConversationRef) -> bool:
        group_id = _onebot_group_id(conversation)
        bot = self.router.for_conversation(conversation)
        if group_id is None or bot is None:
            _log_unavailable(conversation)
            return False
        return await self.probe.can_access(bot, group_id=group_id)

    async def has_member(
        self,
        conversation: ConversationRef,
        *,
        actor: ActorRef,
    ) -> bool:
        group_id = _onebot_group_id(conversation)
        user_id = _onebot_member_id(actor, conversation=conversation)
        bot = self.router.for_conversation(conversation)
        if group_id is None or user_id is None or bot is None:
            _log_unavailable(conversation)
            return False
        return await self.probe.has_member(
            bot,
            group_id=group_id,
            user_id=user_id,
        )


def _onebot_group_id(conversation: ConversationRef) -> int | None:
    if (
        conversation.platform is not Platform.ONEBOT
        or conversation.kind != "group"
        or not conversation.id.isdecimal()
    ):
        return None
    value = int(conversation.id)
    return value if value > 0 else None


def _onebot_member_id(
    actor: ActorRef,
    *,
    conversation: ConversationRef,
) -> int | None:
    if (
        actor.platform is not Platform.ONEBOT
        or actor.kind != "member"
        or actor.scope_id != conversation.id
        or not actor.id.isdecimal()
    ):
        return None
    value = int(actor.id)
    return value if value > 0 else None


def _log_unavailable(conversation: ConversationRef) -> None:
    logger.warning(
        "team audit followup skipped: no compatible connected OneBot bot for "
        "conversation=%s:%s",
        conversation.kind,
        conversation.id,
    )
