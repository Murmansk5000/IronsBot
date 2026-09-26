# SPDX-License-Identifier: MIT
"""Compose messaging services and OneBot delivery adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.integrations.onebot.group_probe import OneBotGroupProbe
from ironsbot.integrations.onebot.messaging_config import (
    build_onebot_message_schedule_targets,
)
from ironsbot.integrations.onebot.team_audit import (
    OneBotTeamAuditMembershipProbe,
    OneBotTeamAuditPolicy,
)
from ironsbot.integrations.sendpic import SendpicBackendProvider
from ironsbot.integrations.storage.team_audit import SqliteTeamAuditReminderStore
from ironsbot.services.messaging.scheduled_outbound import (
    ScheduledMessageOutboundSender,
)
from ironsbot.services.messaging.sendpic import SendpicService
from ironsbot.services.messaging.service import MessagingService
from ironsbot.services.team.audit import TeamAuditService

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
    from ironsbot.integrations.onebot.router import BotRouter
    from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
    from ironsbot.services.bilibili.targets import BiliTargetService
    from ironsbot.services.identity_principals import IdentityPrincipalService
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService


@dataclass(frozen=True, slots=True)
class MessagingComponents:
    """Messaging services assembled from host-specific delivery adapters."""

    messaging: MessagingService
    sendpic: SendpicService
    team_audit: TeamAuditService


def build_messaging_components(  # noqa: PLR0913 - application composition boundary
    settings: Settings,
    http_clients: HttpClients,
    features: FeatureService,
    proactive_delivery: ProactiveMessageDelivery,
    subscriptions: PushUnsubscribeStore,
    bot_router: BotRouter,
    onebot_messenger: OneBotOutboundMessenger,
    bili_targets: BiliTargetService,
    lucky_skin_window: LuckySkinWindowService,
    identity_principals: IdentityPrincipalService,
) -> MessagingComponents:
    """Build configuration-backed messaging, image, and team-audit services."""
    from ironsbot.integrations.onebot.lucky_skin_window import (
        OneBotLuckySkinWindowSubscriptionOptions,
    )

    return MessagingComponents(
        messaging=MessagingService(
            settings.messaging,
            settings.activity,
            subscriptions,
            features,
            ScheduledMessageOutboundSender(
                proactive_delivery,
                identity_principals.official_group_member_for_qq,
            ),
            build_onebot_message_schedule_targets(
                settings.messaging,
                settings.onebot_references,
            ),
            (
                bili_targets.subscription_options,
                OneBotLuckySkinWindowSubscriptionOptions(
                    lucky_skin_window,
                    subscriptions,
                    identity_principals,
                ).subscription_options,
            ),
            _prepare_extra_push_options=bili_targets.prepare_subscription_labels,
            _subscription_submenu_providers=(bili_targets,),
            _mention_reply_targets=tuple(
                tuple(
                    actor
                    for user_index, user in enumerate(action.users)
                    for actor in settings.platform_references.actor_refs(
                        user,
                        location=(
                            "messaging.mention_replies"
                            f"[{action_index}].users[{user_index}]"
                        ),
                    )
                )
                for action_index, action in enumerate(
                    settings.messaging.mention_replies
                )
            ),
            _command_mentions={
                action.id: tuple(
                    settings.onebot_references.actor_refs(
                        action.at_user_ids,
                        location=f"messaging.commands.{action.id}.at_user_ids",
                    )
                )
                for action in (
                    *settings.messaging.commands,
                    *settings.messaging.keyword_replies,
                )
            },
            _actor_principal=identity_principals.actor_principal,
        ),
        sendpic=SendpicService(
            settings.messaging.sendpic,
            SendpicBackendProvider(
                http_clients.cache,
                cnb_token=settings.messaging.sendpic.cnb_token,
                cnb_repo=settings.messaging.sendpic.cnb_repo,
                local_root=settings.messaging.sendpic.local_root,
            ),
            command_starts=tuple(settings.bot.command_start),
        ),
        team_audit=TeamAuditService(
            settings.messaging.team_audit_welcome,
            SqliteTeamAuditReminderStore(settings.paths.runtime_state),
            OneBotTeamAuditPolicy(features),
            onebot_messenger,
            OneBotTeamAuditMembershipProbe(bot_router, OneBotGroupProbe()),
        ),
    )
