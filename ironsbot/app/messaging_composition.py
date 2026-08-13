# SPDX-License-Identifier: MIT
"""Compose messaging services and OneBot delivery adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.integrations.onebot.group_probe import OneBotGroupProbe
from ironsbot.integrations.onebot.messaging_config import (
    build_onebot_message_schedule_targets,
)
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
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
    from ironsbot.integrations.onebot.outbound import GroupOutboundRateLimitService
    from ironsbot.integrations.onebot.router import BotRouter
    from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
    from ironsbot.services.bilibili.targets import BiliTargetService
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
    outbound: GroupOutboundRateLimitService,
    bili_targets: BiliTargetService,
    lucky_skin_window: LuckySkinWindowService,
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
            ScheduledMessageOutboundSender(proactive_delivery),
            build_onebot_message_schedule_targets(
                settings.messaging,
                settings.onebot_references,
            ),
            (
                bili_targets.subscription_options,
                OneBotLuckySkinWindowSubscriptionOptions(
                    lucky_skin_window,
                    subscriptions,
                ).subscription_options,
            ),
            _prepare_extra_push_options=bili_targets.prepare_subscription_labels,
            _subscription_submenu_providers=(bili_targets,),
        ),
        sendpic=SendpicService(
            settings.messaging.sendpic,
            SendpicBackendProvider(
                http_clients.cache,
                cnb_token=settings.messaging.sendpic.cnb_token,
                cnb_repo=settings.messaging.sendpic.cnb_repo,
                local_root=settings.messaging.sendpic.local_root,
            ),
        ),
        team_audit=TeamAuditService(
            settings.messaging.team_audit_welcome,
            SqliteTeamAuditReminderStore(settings.paths.runtime_state),
            OneBotTeamAuditPolicy(features),
            OneBotOutboundMessenger(bot_router, outbound),
            OneBotTeamAuditMembershipProbe(bot_router, OneBotGroupProbe()),
        ),
    )
