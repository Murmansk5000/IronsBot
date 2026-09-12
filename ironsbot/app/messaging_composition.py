# SPDX-License-Identifier: MIT
"""Compose messaging services and OneBot delivery adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import ConversationRef, Platform
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
from ironsbot.integrations.storage.push_topics import SqlitePushTopicStore
from ironsbot.integrations.storage.team_audit import SqliteTeamAuditReminderStore
from ironsbot.services.messaging.scheduled_outbound import (
    ScheduledMessageOutboundSender,
)
from ironsbot.services.messaging.sendpic import SendpicService
from ironsbot.services.messaging.service import MessagingService
from ironsbot.services.messaging.topics import PushTopicService
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

    def resolve_topic_target(
        value: str, source: ConversationRef
    ) -> tuple[ConversationRef, ...]:
        kind, separator, reference = value.partition(":")
        if (
            not separator
            or kind not in {"群", "私聊"}
            or source.platform is not Platform.ONEBOT
        ):
            message = "直发目标格式为 群:群别名 或 私聊:用户别名。"
            raise ValueError(message)
        target_id = (
            settings.onebot_references.resolve_group(
                reference, location="push_topics.direct"
            )
            if kind == "群"
            else settings.onebot_references.resolve_user(
                reference, location="push_topics.direct"
            )
        )
        return (
            ConversationRef(
                Platform.ONEBOT, "group" if kind == "群" else "private", str(target_id)
            ),
        )

    topics = PushTopicService(
        SqlitePushTopicStore(settings.paths.runtime_state),
        proactive_delivery,
        subscriptions,
        features,
        resolve_target=resolve_topic_target,
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
            topics=topics,
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
            OneBotOutboundMessenger(bot_router, outbound),
            OneBotTeamAuditMembershipProbe(bot_router, OneBotGroupProbe()),
        ),
    )
