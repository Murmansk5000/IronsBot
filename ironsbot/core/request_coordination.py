# SPDX-License-Identifier: MIT
"""Unified admission and user-feedback decisions for semantic requests."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from secrets import token_urlsafe
from time import monotonic
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.response_admission import FeedbackOnce

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.core.semantic_requests import SemanticRequest

logger = logging.getLogger(__name__)


class RequestDecisionKind(str, Enum):
    ADMITTED = "admitted"
    RUNNING = "running"
    QUEUED = "queued"
    DUPLICATE = "duplicate"
    SILENT = "silent"


@dataclass(frozen=True, slots=True)
class RequestDecision:
    kind: RequestDecisionKind
    token: object | None = None
    label: str = ""
    feedback: str | None = None

    @property
    def allowed(self) -> bool:
        return self.kind is RequestDecisionKind.ADMITTED

    @property
    def queued(self) -> bool:
        return self.kind is RequestDecisionKind.QUEUED


class SuperuserLookup(Protocol):
    def is_superuser(self, user_id: int) -> bool: ...


class DuplicateResponseConfig(Protocol):
    duplicate_window_seconds: float
    duplicate_message: str


class RequestDecisionSender(Protocol):
    async def __call__(self, decision: RequestDecision) -> None: ...


@dataclass(frozen=True, slots=True)
class RequestToken:
    user_id: int
    scope: str
    request: SemanticRequest
    token_id: str


@dataclass(slots=True)
class _RequestEntry:
    token_id: str
    feedback: FeedbackOnce = field(default_factory=FeedbackOnce)


@dataclass(slots=True)
class _RecentCompletion:
    completed_at: float
    feedback: FeedbackOnce = field(default_factory=FeedbackOnce)


@dataclass(slots=True)
class RequestExecutionFeedback:
    label: str
    sender: RequestDecisionSender
    sent: bool = False

    async def send(self, *, queued: bool) -> None:
        if self.sent:
            return
        self.sent = True
        decision = RequestDecision(
            RequestDecisionKind.QUEUED if queued else RequestDecisionKind.RUNNING,
            label=self.label,
        )
        try:
            await self.sender(decision)
        except Exception:
            logger.exception("request execution feedback failed")


_execution_feedback: ContextVar[RequestExecutionFeedback | None] = ContextVar(
    "request_execution_feedback",
    default=None,
)


@contextmanager
def request_response_scope(
    label: str,
    sender: RequestDecisionSender | None,
) -> Iterator[RequestExecutionFeedback | None]:
    feedback = None if sender is None else RequestExecutionFeedback(label, sender)
    token = _execution_feedback.set(feedback)
    try:
        yield feedback
    finally:
        _execution_feedback.reset(token)


def current_request_response() -> RequestExecutionFeedback | None:
    return _execution_feedback.get()


async def send_request_response(
    *,
    queued: bool,
    feedback: RequestExecutionFeedback | None = None,
) -> None:
    active = current_request_response() if feedback is None else feedback
    if active is not None:
        await active.send(queued=queued)


@dataclass(slots=True)
class RequestCoordinator:
    """Admit one semantic action and coordinate every user-visible decision."""

    features: SuperuserLookup
    config: DuplicateResponseConfig
    _entries: dict[tuple[int, str, str, str], _RequestEntry] = field(
        default_factory=dict
    )
    _recent_completions: dict[tuple[int, str, str, str], _RecentCompletion] = field(
        default_factory=dict
    )

    def admit(
        self,
        *,
        user_id: int,
        request: SemanticRequest,
        scope: str = "private",
        now: float | None = None,
    ) -> RequestDecision:
        if self.features.is_superuser(user_id):
            return RequestDecision(RequestDecisionKind.ADMITTED)

        current_time = monotonic() if now is None else now
        self._prune_recent_completions(current_time)
        normalized_scope = scope.strip() or "private"
        key = (user_id, normalized_scope, request.action.id, request.target.key)
        if entry := self._entries.get(key):
            return self._reject_duplicate(entry)
        if completion := self._recent_completions.get(key):
            return self._reject_duplicate(completion)

        token_id = token_urlsafe(18)
        self._entries[key] = _RequestEntry(token_id=token_id)
        return RequestDecision(
            RequestDecisionKind.ADMITTED,
            token=RequestToken(
                user_id=user_id,
                scope=normalized_scope,
                request=request,
                token_id=token_id,
            ),
        )

    def finish(self, token: object, *, now: float | None = None) -> None:
        released = self._release(token)
        if released is not None:
            key, entry = released
            self._recent_completions[key] = _RecentCompletion(
                completed_at=monotonic() if now is None else now,
                feedback=entry.feedback,
            )

    def release(self, token: object) -> None:
        self._release(token)

    def _release(
        self,
        token: object,
    ) -> tuple[tuple[int, str, str, str], _RequestEntry] | None:
        if not isinstance(token, RequestToken):
            return None
        key = (
            token.user_id,
            token.scope,
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
            if now - completion.completed_at < self.config.duplicate_window_seconds
        }

    def _reject_duplicate(
        self,
        entry: _RequestEntry | _RecentCompletion,
    ) -> RequestDecision:
        feedback = entry.feedback.take(self.config.duplicate_message)
        return RequestDecision(
            RequestDecisionKind.DUPLICATE
            if feedback is not None
            else RequestDecisionKind.SILENT,
            feedback=feedback,
        )

    def reset(self) -> None:
        self._entries.clear()
        self._recent_completions.clear()
