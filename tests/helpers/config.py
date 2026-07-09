from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
    group_commands: list[StubMessageAction] = field(default_factory=list)
    group_schedules: list[StubMessageAction] = field(default_factory=list)
    private_commands: list[StubMessageAction] = field(default_factory=list)
    private_schedules: list[StubMessageAction] = field(default_factory=list)


@dataclass(frozen=True)
class StubTeamResourceConfig:
    subscriptions: list[object] = field(default_factory=list)


@dataclass(frozen=True)
class StubSeerConfig:
    team_resource: StubTeamResourceConfig = field(
        default_factory=StubTeamResourceConfig
    )


@dataclass(frozen=True)
class StubAppConfig:
    ai: StubAiConfig = field(default_factory=StubAiConfig)
    message: StubMessageConfig = field(default_factory=StubMessageConfig)
    seer: StubSeerConfig = field(default_factory=StubSeerConfig)


def stub_app_config(
    *,
    ai_intent_enabled: bool = True,
    team_subscriptions: list[object] | None = None,
    group_actions: list[StubMessageAction] | None = None,
) -> StubAppConfig:
    return StubAppConfig(
        ai=StubAiConfig(intent_actions_enabled=ai_intent_enabled),
        message=StubMessageConfig(group_commands=group_actions or []),
        seer=StubSeerConfig(
            team_resource=StubTeamResourceConfig(
                subscriptions=team_subscriptions or []
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
