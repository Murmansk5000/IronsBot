# SPDX-License-Identifier: MIT
"""Always-on de-duplication for active and recently completed requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from secrets import token_urlsafe
from time import monotonic
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.response_admission import (
    FeedbackOnce,
    ResponseAdmissionDecision,
)

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.core.semantic_requests import SemanticRequest


class SuperuserLookup(Protocol):
    def is_actor_superuser(self, actor: ActorRef) -> bool: ...


@dataclass(frozen=True, slots=True)
class InFlightRequestToken:
    actor: ActorRef
    conversation: ConversationRef
    request: SemanticRequest
    token_id: str
    bot_id: str = ""


InFlightRequestDecision = ResponseAdmissionDecision


class DuplicateWindows(Protocol):
    @property
    def taomee(self) -> float: ...
    @property
    def local(self) -> float: ...
    @property
    def other_network(self) -> float: ...


class DuplicateResponseConfig(Protocol):
    @property
    def duplicate_window_seconds(self) -> DuplicateWindows: ...

    duplicate_message: str


@dataclass(slots=True)
class _InFlightRequestEntry:
    token_id: str
    feedback: FeedbackOnce = field(default_factory=FeedbackOnce)


@dataclass(slots=True)
class _RecentCompletion:
    expires_at: float
    feedback: FeedbackOnce = field(default_factory=FeedbackOnce)


@dataclass(slots=True)
class InFlightRequestService:
    """Reserve a user action within its conversation and suppress duplicates.

    A request stays reserved while it is executing or waiting in a menu FIFO.
    Successful completion uses the action category's configured window. Active
    reservations never expire merely because that window is zero or elapsed.
    """

    features: SuperuserLookup
    config: DuplicateResponseConfig
    _entries: dict[
        tuple[ActorRef, ConversationRef, str, str, str], _InFlightRequestEntry
    ] = field(default_factory=dict)
    _recent_completions: dict[
        tuple[ActorRef, ConversationRef, str, str, str], _RecentCompletion
    ] = field(default_factory=dict)

    def admit(
        self,
        *,
        actor: ActorRef,
        conversation: ConversationRef,
        request: SemanticRequest,
        bot_id: str = "",
        now: float | None = None,
    ) -> InFlightRequestDecision:
        if self.features.is_actor_superuser(actor):
            return InFlightRequestDecision(allowed=True)

        current_time = monotonic() if now is None else now
        self._prune_recent_completions(current_time)
        key = (actor, conversation, bot_id, request.action.id, request.target.key)
        if entry := self._entries.get(key):
            return self._reject_duplicate(entry)
        if completion := self._recent_completions.get(key):
            return self._reject_duplicate(completion)

        token_id = token_urlsafe(18)
        self._entries[key] = _InFlightRequestEntry(token_id=token_id)
        return InFlightRequestDecision(
            allowed=True,
            token=InFlightRequestToken(
                actor=actor,
                conversation=conversation,
                request=request,
                token_id=token_id,
                bot_id=bot_id,
            ),
        )

    def finish(self, token: object, *, now: float | None = None) -> None:
        """Record a handled request so identical replies stay silent briefly."""

        released = self._release(token)
        if released is not None:
            key, entry = released
            assert isinstance(token, InFlightRequestToken)
            category = token.request.action.category
            assert category is not None
            window = getattr(self.config.duplicate_window_seconds, category.value)
            if window == 0:
                return
            self._recent_completions[key] = _RecentCompletion(
                expires_at=(monotonic() if now is None else now) + window,
                feedback=entry.feedback,
            )

    def release(self, token: object) -> None:
        """Drop an unhandled reservation without creating a recent-response key."""

        self._release(token)

    def _release(
        self,
        token: object,
    ) -> (
        tuple[tuple[ActorRef, ConversationRef, str, str, str], _InFlightRequestEntry]
        | None
    ):
        if not isinstance(token, InFlightRequestToken):
            return None
        key = (
            token.actor,
            token.conversation,
            token.bot_id,
            token.request.action.id,
            token.request.target.key,
        )
        entry = self._entries.get(key)
        if entry is not None and entry.token_id == token.token_id:
            self._entries.pop(key, None)
            return key, entry
        return None

    def _prune_recent_completions(self, now: float) -> None:
        self._recent_completions = {
            key: completion
            for key, completion in self._recent_completions.items()
            if now < completion.expires_at
        }

    def _reject_duplicate(
        self,
        entry: _InFlightRequestEntry | _RecentCompletion,
    ) -> InFlightRequestDecision:
        return InFlightRequestDecision(
            allowed=False,
            feedback=entry.feedback.take(self.config.duplicate_message),
        )

    def reset(self) -> None:
        self._entries.clear()
        self._recent_completions.clear()
