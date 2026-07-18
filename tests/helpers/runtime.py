from __future__ import annotations

from dataclasses import dataclass

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.message import (
    OutboundRateLimitConfig,
    PushUnsubscribeConfig,
)
from ironsbot.config.models.runtime import (
    BotRoutingConfig,
    CommandCooldownConfig,
    SuperuserPriorityConfig,
)
from ironsbot.runtime.matchers import MatcherRegistry
from ironsbot.services.admin_priority import AdminPriorityService
from ironsbot.shared.features import FeatureService
from ironsbot.shared.messaging.admin_notice import AdminNoticeService
from ironsbot.shared.messaging.bot_router import BotRouter
from ironsbot.shared.messaging.command_cooldown import CommandCooldownService
from ironsbot.shared.messaging.outbound_rate_limit import (
    GroupOutboundRateLimitService,
)
from ironsbot.shared.messaging.senders import DeliveryResources


@dataclass(frozen=True, slots=True)
class TestRuntime:
    features: FeatureService
    delivery: DeliveryResources
    admin_notices: AdminNoticeService
    priority: AdminPriorityService
    cooldown: CommandCooldownService

    def matcher_registry(self) -> MatcherRegistry:
        return MatcherRegistry(self.cooldown)


def build_test_runtime(  # noqa: PLR0913
    *,
    feature_config: FeatureConfig | None = None,
    superuser_ids: tuple[int, ...] = (),
    outbound_config: OutboundRateLimitConfig | None = None,
    push_unsubscribe: PushUnsubscribeConfig | None = None,
    priority_config: SuperuserPriorityConfig | None = None,
    cooldown_config: CommandCooldownConfig | None = None,
) -> TestRuntime:
    resolved_feature_config = feature_config or FeatureConfig()
    features = FeatureService(
        resolved_feature_config,
        frozenset(superuser_ids),
    )
    delivery = DeliveryResources(
        GroupOutboundRateLimitService(
            outbound_config or OutboundRateLimitConfig(),
            features,
        ),
        push_unsubscribe or PushUnsubscribeConfig(),
        BotRouter(
            BotRoutingConfig(),
            resolved_feature_config.group_aliases,
            resolved_feature_config.user_aliases,
        ),
    )
    return TestRuntime(
        features=features,
        delivery=delivery,
        admin_notices=AdminNoticeService(features, delivery),
        priority=AdminPriorityService(
            priority_config or SuperuserPriorityConfig(),
            features,
        ),
        cooldown=CommandCooldownService(
            cooldown_config or CommandCooldownConfig(),
            features,
        ),
    )
