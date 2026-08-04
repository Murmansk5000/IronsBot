# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


class RequestFeedbackSender(Protocol):
    async def __call__(self, label: str, *, queued: bool) -> None: ...


@dataclass(slots=True)
class RequestFeedback:
    label: str
    sender: RequestFeedbackSender
    sent: bool = False

    async def send(self, *, queued: bool) -> None:
        if self.sent:
            return
        self.sent = True
        try:
            await self.sender(self.label, queued=queued)
        except Exception:
            logger.exception("request admission feedback failed")


_request_feedback: ContextVar[RequestFeedback | None] = ContextVar(
    "request_feedback",
    default=None,
)


@contextmanager
def request_feedback_scope(
    label: str,
    sender: RequestFeedbackSender | None,
) -> Iterator[RequestFeedback | None]:
    feedback = None if sender is None else RequestFeedback(label, sender)
    token = _request_feedback.set(feedback)
    try:
        yield feedback
    finally:
        _request_feedback.reset(token)


async def send_request_feedback(*, queued: bool) -> None:
    if feedback := _request_feedback.get():
        await feedback.send(queued=queued)
