# SPDX-License-Identifier: MIT
"""Platform-neutral semantic identities for executable user requests."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class SemanticRequestError(ValueError):
    @classmethod
    def missing_action(cls) -> SemanticRequestError:
        return cls("semantic action requires an id and label")

    @classmethod
    def missing_target(cls) -> SemanticRequestError:
        return cls("semantic target requires a key and display")


class SemanticRequestSource(str, Enum):
    DIRECT = "direct"
    MENU = "menu"
    AI_INTENT = "ai_intent"
    EXTENSION = "extension"
    BACKGROUND = "background"


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """A stable business action, independent from its command spelling."""

    id: str
    label: str
    cooldown_key: str | None = None

    def __post_init__(self) -> None:
        action_id = self.id.strip()
        label = self.label.strip()
        if not action_id or not label:
            raise SemanticRequestError.missing_action()
        object.__setattr__(self, "id", action_id)
        object.__setattr__(self, "label", label)
        cooldown_key = self.cooldown_key
        object.__setattr__(
            self,
            "cooldown_key",
            action_id if cooldown_key is None else cooldown_key.strip(),
        )


@dataclass(frozen=True, slots=True)
class SemanticTarget:
    """The normalized resource a user action actually operates on."""

    key: str
    display: str

    def __post_init__(self) -> None:
        key = self.key.strip()
        display = self.display.strip()
        if not key or not display:
            raise SemanticRequestError.missing_target()
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "display", display)


@dataclass(frozen=True, slots=True)
class SemanticRequest:
    """One user-visible operation before it reaches a service or protocol."""

    action: ActionDefinition
    target: SemanticTarget
    source: SemanticRequestSource

    def with_source(self, source: SemanticRequestSource) -> SemanticRequest:
        return SemanticRequest(
            action=self.action,
            target=self.target,
            source=source,
        )


@dataclass(frozen=True, slots=True)
class SemanticRequestTrace:
    """Request metadata carried into low-level operation tracing."""

    request: SemanticRequest
    user_id: int | None


_CURRENT_TRACE: ContextVar[SemanticRequestTrace | None] = ContextVar(
    "semantic_request_trace",
    default=None,
)


@contextmanager
def semantic_request_scope(
    request: SemanticRequest | None,
    *,
    user_id: int | None,
) -> Iterator[None]:
    if request is None:
        yield
        return
    token = _CURRENT_TRACE.set(SemanticRequestTrace(request, user_id))
    try:
        yield
    finally:
        _CURRENT_TRACE.reset(token)


def current_semantic_request_trace() -> SemanticRequestTrace | None:
    return _CURRENT_TRACE.get()


def normalized_text_target(value: str) -> SemanticTarget | None:
    normalized = "".join(value.split()).casefold()
    if not normalized:
        return None
    return SemanticTarget(key=normalized, display=value.strip() or normalized)


def singleton_target(key: str = "default", display: str = "默认目标") -> SemanticTarget:
    return SemanticTarget(key=key, display=display)
