from __future__ import annotations

from dataclasses import dataclass

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.config.models.messaging import (
    BotRoutingConfig,
    CommandCooldownConfig,
    OutboundRateLimitConfig,
    PushUnsubscribeConfig,
)
from ironsbot.config.models.settings import MatcherPriorityConfig
from ironsbot.core.features import (
    FeatureConfig,
    FeatureService,
    SuperuserPriorityConfig,
)
from ironsbot.integrations.onebot.delivery import OneBotDelivery
from ironsbot.integrations.onebot.outbound import (
    GroupOutboundRateLimitService,
)
from ironsbot.integrations.onebot.router import BotRouter
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.runtime.matchers import MatcherRegistry, PromptSessionManager
from ironsbot.runtime.priority import AdminPriorityService
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService


@dataclass(frozen=True, slots=True)
class TestRuntime:
    features: FeatureService
    delivery: OneBotDelivery
    admin_notices: AdminNoticeService
    priority: AdminPriorityService
    cooldown: CommandCooldownService
    matcher_priorities: MatcherPriorityConfig
    prompt_sessions: PromptSessionManager
    tasks: TaskOwner

    def matcher_registry(self) -> MatcherRegistry:
        return MatcherRegistry(
            self.cooldown,
            self.matcher_priorities,
            before_reply_send=self.priority.wait,
            prompt_session_manager=self.prompt_sessions,
        )


def build_test_runtime(  # noqa: PLR0913
    *,
    feature_config: FeatureConfig | None = None,
    superuser_ids: tuple[int, ...] = (),
    command_features: frozenset[str] = frozenset(),
    schedule_features: frozenset[str] = frozenset(),
    outbound_config: OutboundRateLimitConfig | None = None,
    push_unsubscribe: PushUnsubscribeConfig | None = None,
    priority_config: SuperuserPriorityConfig | None = None,
    cooldown_config: CommandCooldownConfig | None = None,
    matcher_priority_config: MatcherPriorityConfig | None = None,
) -> TestRuntime:
    resolved_feature_config = feature_config or FeatureConfig()
    features = FeatureService(
        resolved_feature_config,
        frozenset(superuser_ids),
        command_features=command_features,
        schedule_features=schedule_features,
    )
    push_config = push_unsubscribe or PushUnsubscribeConfig()
    tasks = TaskOwner()
    delivery = OneBotDelivery(
        GroupOutboundRateLimitService(
            outbound_config or OutboundRateLimitConfig(),
            features,
            tasks.create,
        ),
        push_config,
        BotRouter(
            BotRoutingConfig(),
            resolved_feature_config.group_aliases,
            resolved_feature_config.user_aliases,
        ),
        PushUnsubscribeStore(push_config.data_path),
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
        matcher_priorities=matcher_priority_config or MatcherPriorityConfig(),
        prompt_sessions=PromptSessionManager(),
        tasks=tasks,
    )
