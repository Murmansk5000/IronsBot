# SPDX-License-Identifier: MIT
"""Keep the triggering message available to operational notices during a query."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.core.message_input import MessageInputContext

_CURRENT_MESSAGE: ContextVar[MessageInputContext | None] = ContextVar(
    "ironsbot_current_message", default=None
)


def current_message_origin() -> MessageInputContext | None:
    return _CURRENT_MESSAGE.get()


@contextmanager
def message_origin(context: MessageInputContext) -> Iterator[None]:
    token = _CURRENT_MESSAGE.set(context)
    try:
        yield
    finally:
        _CURRENT_MESSAGE.reset(token)
