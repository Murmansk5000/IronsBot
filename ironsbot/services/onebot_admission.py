# SPDX-License-Identifier: MIT
"""Framework-free admission of normalized numeric-account transport facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from ironsbot.services.command_errors import CommandErrorReporter

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.own_commands import OwnAccountCommand, OwnAccountInput
    from ironsbot.services.identity_observation import (
        OneBotGroupMessageObservation,
        SilentIdentityObservationService,
    )
    from ironsbot.services.onebot_routing import OneBotRoutingPolicy
    from ironsbot.services.own_commands import OwnAccountCommandPolicy


class AdmissionRejection(str, Enum):
    SILENT = "transport_messages_disabled"
    OWN_MESSAGE = "own_command_not_admitted"
    ROUTING = "conversation_not_owned"
    EVERYONE = "everyone_mention"
    FAILURE = "admission_failed"


@dataclass(frozen=True, slots=True)
class OneBotAdmissionInput:
    context: MessageInputContext | None = None
    observation: OneBotGroupMessageObservation | None = None
    is_group_message: bool = False
    own_input: OwnAccountInput | None = None

    def __post_init__(self) -> None:
        if (
            self.is_group_message or self.observation is not None
        ) and self.context is None:
            msg = "group messages and observations require message context"
            raise ValueError(msg)
        if (
            self.is_group_message
            and self.context is not None
            and (self.context.message.conversation.kind != "group")
        ):
            msg = "group message facts require a group conversation"
            raise ValueError(msg)
        if (
            self.observation is not None
            and self.context is not None
            and (
                self.context.message.actor.id != str(self.observation.sender_id)
                or self.context.message.conversation.kind != "group"
                or self.context.message.conversation.id
                != str(self.observation.group_id)
                or self.context.request_bot_id != str(self.observation.self_id)
            )
        ):
            msg = "mirror evidence must match its normalized source"
            raise ValueError(msg)
        if self.own_input is not None and (
            self.context is None
            or self.own_input.account_id != self.context.request_bot_id
            or self.own_input.conversation != self.context.message.conversation
            or self.own_input.is_own_message != self.is_own_group_message
        ):
            msg = "own command facts must match their normalized source"
            raise ValueError(msg)

    @property
    def is_own_group_message(self) -> bool:
        return (
            self.is_group_message
            and self.context is not None
            and self.context.message.actor.id == self.context.request_bot_id
        )


@dataclass(frozen=True, slots=True)
class OneBotAdmissionDecision:
    rejection: AdmissionRejection | None = None
    own_command: OwnAccountCommand | None = None


@dataclass(frozen=True, slots=True)
class OneBotAdmissionService:
    messages_enabled: bool
    identity_observer: SilentIdentityObservationService | None = None
    self_commands: OwnAccountCommandPolicy | None = None
    routing: OneBotRoutingPolicy | None = None
    errors: CommandErrorReporter = field(default_factory=CommandErrorReporter)

    async def decide(self, incoming: OneBotAdmissionInput) -> OneBotAdmissionDecision:
        context = incoming.context
        if context is None:
            return OneBotAdmissionDecision(
                None if self.messages_enabled else AdmissionRejection.SILENT
            )
        try:
            return await self._decide(incoming)
        except Exception as error:  # noqa: BLE001 - no framework exception details or replies
            await self.errors.report(context, error)
            return OneBotAdmissionDecision(AdmissionRejection.FAILURE)

    async def _decide(self, incoming: OneBotAdmissionInput) -> OneBotAdmissionDecision:
        if self.identity_observer is not None and incoming.observation is not None:
            await self.identity_observer.observe_onebot(incoming.observation)
        if not self.messages_enabled:
            return OneBotAdmissionDecision(AdmissionRejection.SILENT)
        command = None
        if incoming.is_own_group_message:
            if self.self_commands is not None and incoming.own_input is not None:
                command = self.self_commands.accept(incoming.own_input)
            if command is None:
                return OneBotAdmissionDecision(AdmissionRejection.OWN_MESSAGE)
        context = incoming.context
        if incoming.is_group_message and context is not None:
            if (
                self.routing is not None
                and not (command is not None and command.admin_binding)
                and not self.routing.allows_incoming(
                    int(context.request_bot_id), context.message.conversation
                )
            ):
                return OneBotAdmissionDecision(AdmissionRejection.ROUTING)
            if context.mentions_everyone:
                return OneBotAdmissionDecision(AdmissionRejection.EVERYONE)
        return OneBotAdmissionDecision(own_command=command)
