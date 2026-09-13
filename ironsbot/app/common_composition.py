# SPDX-License-Identifier: MIT
"""Compose cross-feature runtime dependencies for the current OneBot host."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.config.models.features import build_onebot_feature_service
from ironsbot.core.promotions import PromotionCatalog
from ironsbot.integrations.onebot.matchers import PromptSessionManager
from ironsbot.integrations.onebot.outbound import (
    GroupOutboundRateLimitService,
    install_outbound_rate_limit_hooks,
)
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.integrations.onebot.router import BotRouter
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.messaging.admin_notice_delivery import OutboundAdminNoticeSender
from ironsbot.services.messaging.proactive_delivery import (
    ProactiveDeliveryPolicy,
    ProactiveMessageDelivery,
)

if TYPE_CHECKING:
    from ironsbot.app.lifecycle import TaskOwner
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService


@dataclass(frozen=True, slots=True)
class CommonComponents:
    """Shared runtime dependencies constructed once per application process."""

    prompt_sessions: PromptSessionManager
    features: FeatureService
    promotions: PromotionCatalog
    outbound: GroupOutboundRateLimitService
    subscriptions: PushUnsubscribeStore
    bot_router: BotRouter
    proactive_delivery: ProactiveMessageDelivery
    admin_notices: AdminNoticeService


def build_common_components(
    settings: Settings,
    task_owner: TaskOwner,
) -> CommonComponents:
    """Build policy, push delivery, and shared interaction primitives."""
    features = build_onebot_feature_service(
        settings.features,
        settings.superuser_ids,
        command_features=settings.messaging.command_feature_keys,
        schedule_features=settings.messaging.schedule_feature_keys,
    )
    outbound = GroupOutboundRateLimitService(
        settings.messaging.outbound_rate_limit,
        features,
        task_owner.create,
    )
    subscriptions = PushUnsubscribeStore(settings.paths.qq_state)
    bot_router = BotRouter(
        settings.messaging.bot_routing,
        settings.onebot_references,
    )
    promotions = PromotionCatalog(settings.promotions)
    proactive_delivery = ProactiveMessageDelivery(
        OneBotOutboundMessenger(bot_router, outbound),
        features,
        promotions,
        subscriptions,
        settings.messaging.push_unsubscribe,
        ProactiveDeliveryPolicy(
            max_attempts=settings.messaging.proactive_delivery.max_attempts,
            max_parallel_targets=(
                settings.messaging.proactive_delivery.max_parallel_targets
            ),
            retry_batch_divisor=(
                settings.messaging.proactive_delivery.retry_batch_divisor
            ),
            retry_delay_seconds=(
                settings.messaging.proactive_delivery.retry_delay_seconds
            ),
        ),
    )
    install_outbound_rate_limit_hooks(outbound)
    return CommonComponents(
        prompt_sessions=PromptSessionManager(),
        features=features,
        promotions=promotions,
        outbound=outbound,
        subscriptions=subscriptions,
        bot_router=bot_router,
        proactive_delivery=proactive_delivery,
        admin_notices=AdminNoticeService(
            features,
            OutboundAdminNoticeSender(proactive_delivery),
        ),
    )
