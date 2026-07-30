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
    from ironsbot.core.semantic_requests import SemanticRequest


class SuperuserLookup(Protocol):
    def is_superuser(self, user_id: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class InFlightRequestToken:
    user_id: int
    request: SemanticRequest
    token_id: str


InFlightRequestDecision = ResponseAdmissionDecision


class DuplicateResponseConfig(Protocol):
    duplicate_window_seconds: float
    duplicate_message: str


@dataclass(slots=True)
class _InFlightRequestEntry:
    token_id: str
    feedback: FeedbackOnce = field(default_factory=FeedbackOnce)


@dataclass(slots=True)
class _RecentCompletion:
    completed_at: float
    feedback: FeedbackOnce = field(default_factory=FeedbackOnce)


@dataclass(slots=True)
class InFlightRequestService:
    """Reserve one real user action and suppress its recent duplicate replies.

    A request stays reserved while it is executing or waiting in a menu FIFO.
    After the handler finishes normally, its semantic identity remains silent
    for one minute. This is deliberately separate from configurable command
    cooldowns: it compares the real business action and target.
    """

    features: SuperuserLookup
    config: DuplicateResponseConfig
    _entries: dict[tuple[int, str, str], _InFlightRequestEntry] = field(
        default_factory=dict
    )
    _recent_completions: dict[tuple[int, str, str], _RecentCompletion] = field(
        default_factory=dict
    )

    def admit(
        self,
        *,
        user_id: int,
        request: SemanticRequest,
        now: float | None = None,
    ) -> InFlightRequestDecision:
        if self.features.is_superuser(user_id):
            return InFlightRequestDecision(allowed=True)

        current_time = monotonic() if now is None else now
        self._prune_recent_completions(current_time)
        key = (user_id, request.action.id, request.target.key)
        if entry := self._entries.get(key):
            return self._reject_duplicate(entry)
        if completion := self._recent_completions.get(key):
            return self._reject_duplicate(completion)

        token_id = token_urlsafe(18)
        self._entries[key] = _InFlightRequestEntry(token_id=token_id)
        return InFlightRequestDecision(
            allowed=True,
            token=InFlightRequestToken(
                user_id=user_id,
                request=request,
                token_id=token_id,
            ),
        )

    def finish(self, token: object, *, now: float | None = None) -> None:
        """Record a handled request so identical replies stay silent briefly."""

        released = self._release(token)
        if released is not None:
            key, entry = released
            self._recent_completions[key] = _RecentCompletion(
                completed_at=monotonic() if now is None else now,
                feedback=entry.feedback,
            )

    def release(self, token: object) -> None:
        """Drop an unhandled reservation without creating a recent-response key."""

        self._release(token)

    def _release(
        self,
        token: object,
    ) -> tuple[tuple[int, str, str], _InFlightRequestEntry] | None:
        if not isinstance(token, InFlightRequestToken):
            return None
        key = (token.user_id, token.request.action.id, token.request.target.key)
        entry = self._entries.get(key)
        if entry is not None and entry.token_id == token.token_id:
            self._entries.pop(key, None)
            return key, entry
        return None

    def _prune_recent_completions(self, now: float) -> None:
        self._recent_completions = {
            key: completion
            for key, completion in self._recent_completions.items()
            if now - completion.completed_at < self.config.duplicate_window_seconds
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
