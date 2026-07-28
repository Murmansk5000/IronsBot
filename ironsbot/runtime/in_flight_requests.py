# SPDX-License-Identifier: MIT
"""Always-on de-duplication for requests that are still executing."""

from __future__ import annotations

from dataclasses import dataclass, field
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ironsbot.core.semantic_requests import SemanticRequest

_DUPLICATE_REQUEST_MESSAGE = (
    "该查询正在处理中；重复的同类请求不会加入队列，后续重复不再提醒。"
)


class SuperuserLookup(Protocol):
    def is_superuser(self, user_id: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class InFlightRequestToken:
    user_id: int
    request: SemanticRequest
    token_id: str


@dataclass(frozen=True, slots=True)
class InFlightRequestDecision:
    allowed: bool
    token: InFlightRequestToken | None = None
    feedback: str | None = None


@dataclass(slots=True)
class _InFlightRequestEntry:
    token_id: str
    feedback_sent: bool = False


@dataclass(slots=True)
class InFlightRequestService:
    """Reserve one real user action until its handling has finished.

    This intentionally has no configuration or cooldown timer. It protects
    only work that is currently active or waiting in a menu FIFO.
    """

    features: SuperuserLookup
    _entries: dict[tuple[int, str, str], _InFlightRequestEntry] = field(
        default_factory=dict
    )

    def admit(
        self,
        *,
        user_id: int,
        request: SemanticRequest,
    ) -> InFlightRequestDecision:
        if self.features.is_superuser(user_id):
            return InFlightRequestDecision(allowed=True)

        key = (user_id, request.action.id, request.target.key)
        if entry := self._entries.get(key):
            feedback = None
            if not entry.feedback_sent:
                entry.feedback_sent = True
                feedback = _DUPLICATE_REQUEST_MESSAGE
            return InFlightRequestDecision(allowed=False, feedback=feedback)

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

    def finish(self, token: object) -> None:
        if not isinstance(token, InFlightRequestToken):
            return
        key = (token.user_id, token.request.action.id, token.request.target.key)
        entry = self._entries.get(key)
        if entry is not None and entry.token_id == token.token_id:
            self._entries.pop(key, None)

    def reset(self) -> None:
        self._entries.clear()
