# SPDX-License-Identifier: MIT
"""Platform-neutral contracts shared by matcher registration and prompts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypeAlias

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.typing import T_State

from ironsbot.runtime.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    normalized_text_target,
)

if TYPE_CHECKING:
    from ironsbot.core.semantic_requests import SemanticTarget

CommandIdResolver: TypeAlias = Callable[[MessageEvent, T_State], str | None]
CommandIdSource: TypeAlias = str | CommandIdResolver
SemanticRequestResolver: TypeAlias = Callable[
    [MessageEvent, T_State], SemanticRequest | None
]
QueuedSemanticRequestResolver: TypeAlias = SemanticRequestResolver


def static_command_id(command_id: str) -> CommandIdResolver:
    def resolve(_event: MessageEvent, _state: T_State) -> str:
        return command_id

    return resolve


def default_semantic_target(
    event: MessageEvent,
    _state: T_State,
) -> SemanticTarget | None:
    return normalized_text_target(event.get_plaintext())


def default_semantic_request(
    *,
    command_id: str,
    label: str,
    event: MessageEvent,
    state: T_State,
) -> SemanticRequest | None:
    """Build the default identity for commands without a custom resolver."""

    target = default_semantic_target(event, state)
    if target is None:
        return None
    return SemanticRequest(
        action=ActionDefinition(
            id=command_id,
            label=label,
            cooldown_key=command_id,
        ),
        target=target,
        source=SemanticRequestSource.DIRECT,
    )


class CooldownDecision(Protocol):
    @property
    def allowed(self) -> bool: ...

    @property
    def token(self) -> object | None: ...

    @property
    def feedback(self) -> str | None: ...


class CommandCooldown(Protocol):
    def admit(
        self,
        *,
        user_id: int,
        command_id: str,
        now: float | None = None,
    ) -> CooldownDecision: ...

    def finish(self, token: object) -> None: ...


class CommandPolicyError(ValueError):
    @classmethod
    def ambiguous(cls) -> CommandPolicyError:
        return cls("command policy requires exactly one command id or exemption")

    @classmethod
    def empty_exemption(cls) -> CommandPolicyError:
        return cls("command policy exemption reason must not be empty")

    @classmethod
    def exempt_with_semantic_request(cls) -> CommandPolicyError:
        return cls("exempt command policy cannot define a semantic request")

    @classmethod
    def exempt_with_help_ids(cls) -> CommandPolicyError:
        return cls("exempt command policy cannot define help ids")

    @classmethod
    def exempt_with_conversation_close(cls) -> CommandPolicyError:
        return cls("exempt command policy cannot close an active conversation")

    @classmethod
    def empty_help_id(cls) -> CommandPolicyError:
        return cls("command policy help ids must not contain empty values")


@dataclass(frozen=True, slots=True)
class CommandPolicy:
    """Admission and conversation ownership rules for a registered command."""

    command_id: CommandIdSource | None = None
    exemption_reason: str | None = None
    semantic_request: SemanticRequestResolver | None = None
    help_ids: tuple[str, ...] = ()
    closes_active_conversation: bool = True

    def __post_init__(self) -> None:
        if (self.command_id is None) == (self.exemption_reason is None):
            raise CommandPolicyError.ambiguous()
        if self.exemption_reason is not None and not self.exemption_reason.strip():
            raise CommandPolicyError.empty_exemption()
        if self.exemption_reason is not None and self.semantic_request is not None:
            raise CommandPolicyError.exempt_with_semantic_request()
        if self.exemption_reason is not None and self.help_ids:
            raise CommandPolicyError.exempt_with_help_ids()
        if self.exemption_reason is not None and self.closes_active_conversation:
            raise CommandPolicyError.exempt_with_conversation_close()
        if any(not command_id.strip() for command_id in self.help_ids):
            raise CommandPolicyError.empty_help_id()

    @classmethod
    def command(
        cls,
        command_id: CommandIdSource,
        *,
        semantic_request: SemanticRequestResolver | None = None,
        help_ids: tuple[str, ...] = (),
        closes_active_conversation: bool = True,
    ) -> CommandPolicy:
        return cls(
            command_id=command_id,
            semantic_request=semantic_request,
            help_ids=help_ids,
            closes_active_conversation=closes_active_conversation,
        )

    @classmethod
    def exempt(cls, reason: str) -> CommandPolicy:
        return cls(exemption_reason=reason, closes_active_conversation=False)
