from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.message import (
    OutboundRateLimitConfig,
    PushUnsubscribeConfig,
    TeamAuditWelcomeConfig,
)
from ironsbot.config.models.runtime import BotRoutingConfig, HelpConfig, LoggingConfig
from ironsbot.config.models.seer import (
    MintmarkQueryConfig,
    RankQueryConfig,
    SeasonCountdownConfig,
)

if TYPE_CHECKING:
    from ironsbot.config.models.seer import TeamResourceConfig


@dataclass(frozen=True)
class StubAiConfig:
    intent_actions_enabled: bool = True
    memory: bool = True
    memory_path: Path = Path("data/ai_chat/memory.sqlite")
    memory_turns: int = 8
    memory_max_chars: int = 1200


@dataclass(frozen=True)
class StubMessageAction:
    enabled: bool
    feature: str


@dataclass(frozen=True)
class StubMessageConfig:
    outbound_rate_limit: OutboundRateLimitConfig = field(
        default_factory=OutboundRateLimitConfig
    )
    push_unsubscribe: PushUnsubscribeConfig = field(
        default_factory=PushUnsubscribeConfig
    )
    team_audit_welcome: TeamAuditWelcomeConfig = field(
        default_factory=TeamAuditWelcomeConfig
    )
    group_commands: list[StubMessageAction] = field(default_factory=list)
    group_schedules: list[StubMessageAction] = field(default_factory=list)
    private_commands: list[StubMessageAction] = field(default_factory=list)
    private_schedules: list[StubMessageAction] = field(default_factory=list)


@dataclass(frozen=True)
class StubTeamResourceConfig:
    subscriptions: list[object] = field(default_factory=list)


@dataclass(frozen=True)
class StubSeerConfig:
    mintmark: MintmarkQueryConfig = field(default_factory=MintmarkQueryConfig)
    rank: RankQueryConfig = field(default_factory=RankQueryConfig)
    season: SeasonCountdownConfig = field(default_factory=SeasonCountdownConfig)
    team_resource: TeamResourceConfig | StubTeamResourceConfig = field(
        default_factory=StubTeamResourceConfig
    )


@dataclass(frozen=True)
class StubRuntimeConfig:
    bot_routing: BotRoutingConfig = field(default_factory=BotRoutingConfig)
    help: HelpConfig = field(default_factory=HelpConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


@dataclass(frozen=True)
class StubAppConfig:
    activity: ActivityConfig = field(default_factory=ActivityConfig)
    feature: FeatureConfig = field(default_factory=FeatureConfig)
    ai: StubAiConfig = field(default_factory=StubAiConfig)
    message: StubMessageConfig = field(default_factory=StubMessageConfig)
    runtime: StubRuntimeConfig = field(default_factory=StubRuntimeConfig)
    seer: StubSeerConfig = field(default_factory=StubSeerConfig)


def stub_app_config(  # noqa: PLR0913
    *,
    activity_config: ActivityConfig | None = None,
    ai_intent_enabled: bool = True,
    bot_routing_config: BotRoutingConfig | None = None,
    feature_config: FeatureConfig | None = None,
    logging_config: LoggingConfig | None = None,
    mintmark_config: MintmarkQueryConfig | None = None,
    outbound_rate_limit_config: OutboundRateLimitConfig | None = None,
    push_unsubscribe_config: PushUnsubscribeConfig | None = None,
    rank_config: RankQueryConfig | None = None,
    season_config: SeasonCountdownConfig | None = None,
    team_audit_welcome_config: TeamAuditWelcomeConfig | None = None,
    team_resource_config: TeamResourceConfig | None = None,
    team_subscriptions: list[object] | None = None,
    group_actions: list[StubMessageAction] | None = None,
) -> StubAppConfig:
    return StubAppConfig(
        activity=activity_config or ActivityConfig(),
        feature=feature_config or FeatureConfig(),
        ai=StubAiConfig(intent_actions_enabled=ai_intent_enabled),
        message=StubMessageConfig(
            outbound_rate_limit=(
                outbound_rate_limit_config or OutboundRateLimitConfig()
            ),
            push_unsubscribe=push_unsubscribe_config or PushUnsubscribeConfig(),
            team_audit_welcome=(
                team_audit_welcome_config or TeamAuditWelcomeConfig()
            ),
            group_commands=group_actions or [],
        ),
        runtime=StubRuntimeConfig(
            bot_routing=bot_routing_config or BotRoutingConfig(),
            logging=logging_config or LoggingConfig(),
        ),
        seer=StubSeerConfig(
            mintmark=mintmark_config or MintmarkQueryConfig(),
            rank=rank_config or RankQueryConfig(),
            season=season_config or SeasonCountdownConfig(),
            team_resource=(
                team_resource_config
                or StubTeamResourceConfig(subscriptions=team_subscriptions or [])
            )
        ),
    )


def stub_ai_memory_config(
    *,
    memory_path: Path,
    memory_turns: int = 1,
    memory_max_chars: int = 200,
) -> StubAiConfig:
    return StubAiConfig(
        memory=True,
        memory_path=memory_path,
        memory_turns=memory_turns,
        memory_max_chars=memory_max_chars,
    )
