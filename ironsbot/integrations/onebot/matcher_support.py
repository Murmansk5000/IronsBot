# SPDX-License-Identifier: MIT
"""Low-level callback and runtime-context helpers for OneBot matchers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from inspect import Signature, signature
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.matcher import Matcher

    from ironsbot.runtime.in_flight_requests import InFlightRequestService


T = TypeVar("T")
RUNTIME_CONTEXT_TOKEN_STATE_KEY = "_ironsbot_runtime_context_token"
EXPLICIT_COMMAND_STATE_KEY = "_ironsbot_explicit_command"


class _BoundPartial(partial):
    @property
    def __globals__(self) -> dict[str, Any]:
        """Expose wrapped globals for NoneBot dependency parsing."""

        return cast("dict[str, Any]", getattr(self.func, "__globals__", {}))

    @property
    def __signature__(self) -> Signature:
        """Hide arguments supplied by application composition."""

        original = signature(self.func)
        try:
            supplied = original.bind_partial(*self.args, **(self.keywords or {}))
        except TypeError:
            return original
        return original.replace(
            parameters=[
                parameter
                for name, parameter in original.parameters.items()
                if name not in supplied.arguments
            ]
        )


class _AsyncPartial(_BoundPartial):
    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        result: Awaitable[Any] = super().__call__(*args, **kwargs)
        return await result


def bind(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> Callable[..., T]:
    """Bind a synchronous callback without hiding its annotations."""

    return cast("Callable[..., T]", _BoundPartial(func, *args, **kwargs))


def bind_async(
    func: Callable[..., Awaitable[T]], /, *args: Any, **kwargs: Any
) -> Callable[..., Awaitable[T]]:
    """Bind asynchronous callbacks while preserving their awaitable signature."""

    return cast("Callable[..., Awaitable[T]]", _AsyncPartial(func, *args, **kwargs))


@dataclass(frozen=True, slots=True)
class _MatcherRuntimeContext:
    in_flight_requests: InFlightRequestService | None


_MATCHER_RUNTIME_CONTEXTS: dict[str, _MatcherRuntimeContext] = {}


def register_runtime_context(
    in_flight_requests: InFlightRequestService | None,
) -> str | None:
    """Store composition-owned matcher services and return an opaque token."""

    if in_flight_requests is None:
        return None
    token = token_urlsafe(18)
    _MATCHER_RUNTIME_CONTEXTS[token] = _MatcherRuntimeContext(
        in_flight_requests=in_flight_requests,
    )
    return token


def get_runtime_context(
    source: Matcher | dict[Any, Any],
) -> _MatcherRuntimeContext | None:
    state = source if isinstance(source, dict) else source.state
    token = state.get(RUNTIME_CONTEXT_TOKEN_STATE_KEY)
    if not isinstance(token, str):
        return None
    return _MATCHER_RUNTIME_CONTEXTS.get(token)
