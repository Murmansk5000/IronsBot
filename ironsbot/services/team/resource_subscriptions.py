# SPDX-License-Identifier: MIT
"""Platform-neutral team resource subscription state and command parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple, Protocol

from ironsbot.core.platform import ActorRef, ConversationRef

if TYPE_CHECKING:
    from collections.abc import Sequence

_ADD_PREFIXES = ("订阅战队", "添加战队", "战队订阅")
_REMOVE_PREFIXES = ("取消订阅战队", "删除订阅战队", "战队取消订阅")
_LIST_COMMANDS = ("战队订阅", "订阅战队", "本群战队")


class TeamResourceSubscriptionTarget(NamedTuple):
    """The conversation or actor that owns a resource subscription."""

    recipient: ConversationRef | ActorRef
    mention_actors: tuple[ActorRef, ...] = ()

    @property
    def conversation(self) -> ConversationRef | None:
        return self.recipient if isinstance(self.recipient, ConversationRef) else None

    @property
    def actor(self) -> ActorRef | None:
        return self.recipient if isinstance(self.recipient, ActorRef) else None

    @property
    def is_group(self) -> bool:
        return self.conversation is not None and self.conversation.kind == "group"

    @property
    def is_private(self) -> bool:
        return self.actor is not None


class TeamResourceSubscription(NamedTuple):
    conversation: ConversationRef
    team_id: int
    team_name: str
    threshold: int
    mention_actors: tuple[ActorRef, ...]
    created_by: ActorRef
    updated_by: ActorRef
    created_at: str
    updated_at: str


class TeamResourceSubscriptionUpdate(NamedTuple):
    conversation: ConversationRef
    team_id: int
    team_name: str
    threshold: int
    mention_actors: tuple[ActorRef, ...]
    operator: ActorRef


class TeamResourcePrivateSubscription(NamedTuple):
    actor: ActorRef
    team_id: int
    team_name: str
    threshold: int
    created_at: str
    updated_at: str


class TeamResourcePrivateSubscriptionUpdate(NamedTuple):
    actor: ActorRef
    team_id: int
    team_name: str
    threshold: int


class TeamResourceSubscriptionPrompt(NamedTuple):
    conversation: ConversationRef
    team_id: int
    team_name: str
    prompted_by: ActorRef
    prompted_at: str
    handled_by: ActorRef | None = None
    handled_at: str | None = None
    accepted: bool | None = None

    @property
    def is_pending(self) -> bool:
        return self.handled_at is None


@dataclass(frozen=True, slots=True)
class TeamResourceManageCommand:
    action: Literal["add", "remove", "list"]
    team_id: int | None = None
    threshold: int | None = None
    has_manual_mention: bool = False


class TeamResourceStore(Protocol):
    def list_all(self) -> list[TeamResourceSubscription]: ...
    def list_conversation(
        self,
        conversation: ConversationRef,
    ) -> list[TeamResourceSubscription]: ...
    def upsert(self, update: TeamResourceSubscriptionUpdate) -> None: ...
    def list_all_private(self) -> list[TeamResourcePrivateSubscription]: ...
    def list_actor(self, actor: ActorRef) -> list[TeamResourcePrivateSubscription]: ...
    def upsert_private(self, update: TeamResourcePrivateSubscriptionUpdate) -> None: ...
    def has_prompted_conversation(self, conversation: ConversationRef) -> bool: ...
    def get_pending_prompt(
        self,
        conversation: ConversationRef,
    ) -> TeamResourceSubscriptionPrompt | None: ...
    def mark_conversation_prompted(
        self,
        *,
        conversation: ConversationRef,
        team_id: int,
        team_name: str,
        prompted_by: ActorRef,
    ) -> None: ...
    def mark_prompt_handled(
        self,
        *,
        conversation: ConversationRef,
        handled_by: ActorRef,
        accepted: bool,
    ) -> None: ...
    def update_team_name(
        self,
        *,
        conversation: ConversationRef,
        team_id: int,
        team_name: str,
    ) -> None: ...
    def delete(
        self,
        *,
        conversation: ConversationRef,
        team_id: int,
    ) -> bool: ...
    def update_private_team_name(
        self,
        *,
        actor: ActorRef,
        team_id: int,
        team_name: str,
    ) -> None: ...
    def delete_private(self, *, actor: ActorRef, team_id: int) -> bool: ...


def parse_team_resource_manage_command(
    text: str,
) -> TeamResourceManageCommand | None:
    stripped = re.sub(r"\s+", " ", text.strip())
    manual_mention = re.search(r"@\d{5,}", stripped) is not None
    if stripped in _LIST_COMMANDS:
        return TeamResourceManageCommand("list")

    for action in ("remove", "add"):
        prefixes = _REMOVE_PREFIXES if action == "remove" else _ADD_PREFIXES
        for prefix in prefixes:
            if not stripped.startswith(prefix):
                continue
            rest = stripped[len(prefix) :].strip()
            match = re.match(r"\d+", rest)
            if match is None:
                return TeamResourceManageCommand("list")
            threshold_match = re.search(
                r"(?<!\S)(\d+)(?!\S)",
                rest[match.end() :],
            )
            return TeamResourceManageCommand(
                action,
                int(match.group()),
                (
                    int(threshold_match.group(1))
                    if action == "add" and threshold_match is not None
                    else None
                ),
                manual_mention,
            )
    return None


def format_subscription_actors(actors: Sequence[ActorRef]) -> str:
    return "、".join(actor.id for actor in actors) if actors else "无"
