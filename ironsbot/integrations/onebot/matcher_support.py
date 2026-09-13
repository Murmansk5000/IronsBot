# SPDX-License-Identifier: MIT
"""Low-level callback and runtime-context helpers for OneBot matchers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from inspect import Signature, signature
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any, TypeVar, cast

from ironsbot.integrations.onebot.prompt_errors import (
    PromptSessionManagerMissingError,
)
from ironsbot.integrations.onebot.prompt_sessions import (
    GroupMenuAnchor,
    PromptSessionManager,
)

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.matcher import Matcher

    from ironsbot.integrations.onebot.prompt_sessions import _QueuedConversation
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
    prompt_session_manager: PromptSessionManager | None
    in_flight_requests: InFlightRequestService | None


_MATCHER_RUNTIME_CONTEXTS: dict[str, _MatcherRuntimeContext] = {}


def register_runtime_context(
    prompt_session_manager: PromptSessionManager | None,
    in_flight_requests: InFlightRequestService | None,
) -> str | None:
    """Store composition-owned matcher services and return an opaque token."""

    if prompt_session_manager is None and in_flight_requests is None:
        return None
    token = token_urlsafe(18)
    _MATCHER_RUNTIME_CONTEXTS[token] = _MatcherRuntimeContext(
        prompt_session_manager=prompt_session_manager,
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


def get_prompt_session_manager(
    source: Matcher | dict[Any, Any],
) -> PromptSessionManager:
    context = get_runtime_context(source)
    manager = None if context is None else context.prompt_session_manager
    if not isinstance(manager, PromptSessionManager):
        raise PromptSessionManagerMissingError
    return manager


def get_queued_conversation(
    source: Matcher | dict[Any, Any],
) -> _QueuedConversation | None:
    try:
        return get_prompt_session_manager(source).queued_conversation(
            source if isinstance(source, dict) else source.state
        )
    except PromptSessionManagerMissingError:
        return None


def queued_conversation_is_cancelled(source: Matcher | dict[Any, Any]) -> bool:
    state = source if isinstance(source, dict) else source.state
    try:
        return get_prompt_session_manager(source).queued_conversation_is_cancelled(
            state
        )
    except PromptSessionManagerMissingError:
        return False


def update_queued_reply_check(
    matcher: Matcher,
    reply_check: Callable[[Event], bool],
    *,
    group_reply_check: Callable[[Event], bool] | None = None,
) -> None:
    context = get_queued_conversation(matcher)
    if context is not None:
        context.update_reply_check(reply_check, group_reply_check)


def update_queued_menu_anchor(
    matcher: Matcher,
    event: Event,
    send_result: object,
) -> None:
    """Replace the shared-reply anchor after sending a group menu."""

    context = get_queued_conversation(matcher)
    if context is not None:
        context.update_menu_anchor(group_menu_anchor(event, send_result))


def group_menu_anchor(event: Event, send_result: object) -> GroupMenuAnchor | None:
    group_id = getattr(event, "group_id", None)
    bot_user_id = getattr(event, "self_id", None)
    message_id = _send_result_message_id(send_result)
    if (
        not isinstance(group_id, int)
        or not isinstance(bot_user_id, int)
        or bot_user_id <= 0
        or message_id is None
    ):
        return None
    return GroupMenuAnchor(
        group_id=group_id,
        bot_user_id=bot_user_id,
        message_id=message_id,
    )


def _send_result_message_id(send_result: object) -> int | None:
    raw_message_id = (
        send_result.get("message_id")
        if isinstance(send_result, Mapping)
        else getattr(send_result, "message_id", None)
    )
    if isinstance(raw_message_id, bool) or not isinstance(raw_message_id, (int, str)):
        return None
    try:
        message_id = int(raw_message_id)
    except (TypeError, ValueError):
        return None
    return message_id if message_id > 0 else None
