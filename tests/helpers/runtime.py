from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.config.models.features import (
    FeatureConfig,
    build_onebot_feature_service,
)
from ironsbot.config.models.messaging import (
    BotRoutingConfig,
    CommandCooldownConfig,
    OutboundRateLimitConfig,
    PushUnsubscribeConfig,
)
from ironsbot.config.models.settings import MatcherPriorityConfig
from ironsbot.config.onebot_references import OneBotReferenceResolver
from ironsbot.integrations.onebot.admin_notice import OneBotAdminNoticeSender
from ironsbot.integrations.onebot.delivery import OneBotDelivery
from ironsbot.integrations.onebot.matchers import MatcherFactory, PromptSessionManager
from ironsbot.integrations.onebot.outbound import (
    GroupOutboundRateLimitService,
)
from ironsbot.integrations.onebot.router import BotRouter
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.runtime.in_flight_requests import InFlightRequestService
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService


@dataclass(frozen=True, slots=True)
class TestRuntime:
    features: FeatureService
    onebot_references: OneBotReferenceResolver
    delivery: OneBotDelivery
    admin_notices: AdminNoticeService
    cooldown: CommandCooldownService
    in_flight_requests: InFlightRequestService
    matcher_priorities: MatcherPriorityConfig
    prompt_sessions: PromptSessionManager
    tasks: TaskOwner

    def matcher_factory(self) -> MatcherFactory:
        return MatcherFactory(
            self.cooldown,
            self.matcher_priorities,
            prompt_session_manager=self.prompt_sessions,
            in_flight_requests=self.in_flight_requests,
        )


def build_test_runtime(  # noqa: PLR0913
    *,
    feature_config: FeatureConfig | None = None,
    superuser_ids: tuple[int, ...] = (),
    command_features: frozenset[str] = frozenset(),
    schedule_features: frozenset[str] = frozenset(),
    outbound_config: OutboundRateLimitConfig | None = None,
    push_unsubscribe: PushUnsubscribeConfig | None = None,
    state_path: Path | None = None,
    cooldown_config: CommandCooldownConfig | None = None,
    matcher_priority_config: MatcherPriorityConfig | None = None,
) -> TestRuntime:
    resolved_feature_config = feature_config or FeatureConfig()
    isolated_state_path = state_path or _isolated_state_path()
    features = build_onebot_feature_service(
        resolved_feature_config,
        frozenset(superuser_ids),
        command_features=command_features,
        schedule_features=schedule_features,
    )
    push_config = push_unsubscribe or PushUnsubscribeConfig()
    tasks = TaskOwner()
    onebot_references = OneBotReferenceResolver(
        resolved_feature_config.group_aliases,
        resolved_feature_config.user_aliases,
    )
    delivery = OneBotDelivery(
        GroupOutboundRateLimitService(
            outbound_config or OutboundRateLimitConfig(),
            features,
            tasks.create,
        ),
        push_config,
        BotRouter(
            BotRoutingConfig(),
            onebot_references,
        ),
        PushUnsubscribeStore(isolated_state_path),
    )
    return TestRuntime(
        features=features,
        onebot_references=onebot_references,
        delivery=delivery,
        admin_notices=AdminNoticeService(
            features,
            OneBotAdminNoticeSender(delivery),
        ),
        cooldown=CommandCooldownService(
            cooldown_config or CommandCooldownConfig(),
            features,
        ),
        in_flight_requests=InFlightRequestService(
            features,
            cooldown_config or CommandCooldownConfig(),
        ),
        matcher_priorities=matcher_priority_config or MatcherPriorityConfig(),
        prompt_sessions=PromptSessionManager(),
        tasks=tasks,
    )


def _isolated_state_path() -> Path:
    temp_root = Path(os.environ.get("TEMP", Path.cwd()))
    return temp_root / f"ironsbot-test-state-{uuid4().hex}.sqlite"
