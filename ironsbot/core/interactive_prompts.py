# SPDX-License-Identifier: MIT
"""Platform-neutral identities and inputs for finite interactive prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import is_supported_message_actor

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef, ConversationRef

_ACTION_PREFIX = "ironsbot:prompt:"


@dataclass(frozen=True, slots=True)
class PromptChoice:
    id: str
    label: str
    text_inputs: frozenset[str]
    is_visible: bool = True

    def __post_init__(self) -> None:
        normalized_inputs = frozenset(
            normalized
            for value in self.text_inputs
            if (normalized := value.strip().casefold())
        )
        object.__setattr__(self, "text_inputs", normalized_inputs)
        if not self.id or not self.label.strip() or not normalized_inputs:
            msg = "prompt choices require an id, label, and text input"
            raise ValueError(msg)

    def accepts_text(self, text: str) -> bool:
        normalized = text.strip().casefold()
        return normalized in self.text_inputs


@dataclass(frozen=True, slots=True)
class PromptSession:
    id: str
    actor: ActorRef
    conversation: ConversationRef
    request_message_id: str
    choices: tuple[PromptChoice, ...]
    expires_at: float

    def __post_init__(self) -> None:
        if not self.id or not self.request_message_id.strip() or not self.choices:
            msg = "prompt sessions require an id, request message, and choices"
            raise ValueError(msg)
        if not is_supported_message_actor(self.actor, self.conversation):
            msg = "prompt actor and conversation do not match"
            raise ValueError(msg)
        choice_ids = tuple(choice.id for choice in self.choices)
        if len(choice_ids) != len(set(choice_ids)):
            msg = "prompt choice ids must be unique"
            raise ValueError(msg)

    def choice_from_text(self, text: str) -> PromptChoice | None:
        matches = tuple(choice for choice in self.choices if choice.accepts_text(text))
        return matches[0] if len(matches) == 1 else None

    def action_data(self, choice: PromptChoice) -> str:
        if choice not in self.choices:
            msg = "prompt choice does not belong to this session"
            raise ValueError(msg)
        return f"{_ACTION_PREFIX}{self.id}:{choice.id}"

    def choice_from_action(self, action_data: str) -> PromptChoice | None:
        prefix = f"{_ACTION_PREFIX}{self.id}:"
        if not action_data.startswith(prefix):
            return None
        choice_id = action_data.removeprefix(prefix)
        return next((choice for choice in self.choices if choice.id == choice_id), None)
