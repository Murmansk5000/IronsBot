# SPDX-License-Identifier: MIT
"""OneBot delivery and configuration adapters for team resource notices."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, Platform
from ironsbot.integrations.onebot.target_refs import (
    is_onebot_group_conversation,
    is_onebot_private_actor,
)
from ironsbot.integrations.onebot.targets import OneBotMessageTarget

if TYPE_CHECKING:
    from ironsbot.config.models.seer import TeamResourceConfig
    from ironsbot.config.onebot_references import OneBotReferenceResolver
    from ironsbot.integrations.onebot.delivery import OneBotDelivery
    from ironsbot.services.team.resource import TeamResourceSubscriptionTarget


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OneBotTeamResourceNoticeSender:
    """Keep QQ routing and legacy delivery policy at the OneBot edge."""

    delivery: OneBotDelivery

    async def send_low_resource_notice(
        self,
        target: TeamResourceSubscriptionTarget,
        message: str,
    ) -> bool:
        message_target = _onebot_message_target(target)
        if message_target is None:
            _LOGGER.warning(
                "team resource notice skipped unsupported target: %r",
                target.recipient,
            )
            return False
        summary = await self.delivery.send_targets(
            [message_target],
            message,
            action_name="team resource subscription notice",
            interval_seconds=0,
        )
        return bool(summary.succeeded)


def build_onebot_team_resource_default_mentions(
    config: TeamResourceConfig,
    references: OneBotReferenceResolver,
) -> tuple[ActorRef, ...]:
    """Resolve OneBot-only TOML aliases before the service is composed."""

    return tuple(
        ActorRef(Platform.ONEBOT, str(user_id))
        for user_id in references.resolve_users(
            config.default_at_users,
            location="seer.team_resource.default_at_users",
        )
    )


def _onebot_message_target(
    target: TeamResourceSubscriptionTarget,
) -> OneBotMessageTarget | None:
    conversation = target.conversation
    if conversation is not None:
        if not is_onebot_group_conversation(conversation):
            return None
        mention_ids = tuple(
            int(actor.id)
            for actor in target.mention_actors
            if is_onebot_private_actor(actor)
        )
        invalid_mentions = len(mention_ids) != len(target.mention_actors)
        if invalid_mentions:
            _LOGGER.warning("team resource notice ignored unsupported mention actors")
        return OneBotMessageTarget("group", int(conversation.id), mention_ids)

    actor = target.actor
    if actor is None or not is_onebot_private_actor(actor):
        return None
    return OneBotMessageTarget("private", int(actor.id))
