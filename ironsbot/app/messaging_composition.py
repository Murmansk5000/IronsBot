# SPDX-License-Identifier: MIT
"""Compose shared messaging services and platform delivery adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.config.message_schedule_targets import (
    build_message_schedule_targets,
)
from ironsbot.integrations.onebot.group_probe import OneBotGroupProbe
from ironsbot.integrations.onebot.team_audit import (
    OneBotTeamAuditMembershipProbe,
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
from ironsbot.services.team.audit_policy import FeatureTeamAuditPolicy

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.platform import ConversationRef
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
    from ironsbot.integrations.onebot.router import BotRouter
    from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
    from ironsbot.services.bilibili.targets import BiliTargetService
    from ironsbot.services.identity_principals import IdentityPrincipalService
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
    from ironsbot.services.private_conversation_routes import PrivateConversationRoutes
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
    private_routes: PrivateConversationRoutes,
    transaction_spawn: TaskSpawner,
) -> MessagingComponents:
    """Build configuration-backed messaging, image, and team-audit services."""
    from ironsbot.services.seer.lucky_skin_window_subscriptions import (
        LuckySkinWindowSubscriptionOptions,
    )

    def resolve_topic_target(
        value: str, source: ConversationRef
    ) -> tuple[ConversationRef, ...]:
        kind, separator, reference = value.partition(":")
        if not separator or kind not in {"群", "私聊"}:
            msg = "直发目标格式为 群:群别名 或 私聊:用户别名。"
            raise ValueError(msg)
        resolver = settings.platform_references
        targets = (
            resolver.group_conversation_refs(reference, location="push_topics.direct")
            if kind == "群"
            else resolver.private_conversation_refs(
                reference,
                location="push_topics.direct",
            )
        )
        return tuple(
            target
            for target in targets
            if target.platform == source.platform
            and target.account_id == source.account_id
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
            ScheduledMessageOutboundSender(
                proactive_delivery,
                identity_principals.official_group_member_for_qq,
            ),
            build_message_schedule_targets(
                settings.messaging,
                settings.qq_references,
            ),
            (
                bili_targets.subscription_options,
                LuckySkinWindowSubscriptionOptions(
                    lucky_skin_window,
                    subscriptions,
                    identity_principals,
                    private_routes,
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
                    settings.qq_references.actor_refs(
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
            _private_routes=private_routes,
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
            SqliteTeamAuditReminderStore(
                settings.paths.runtime_state, spawn=transaction_spawn
            ),
            FeatureTeamAuditPolicy(features),
            onebot_messenger,
            OneBotTeamAuditMembershipProbe(bot_router, OneBotGroupProbe()),
        ),
    )
