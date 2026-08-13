"""Durable matcher callbacks for queued menu conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.adapters import Event  # noqa: TC002 - driver resolves annotations.
from nonebot.dependencies import Dependent
from nonebot.matcher import Matcher  # noqa: TC002 - driver resolves annotations.
from nonebot.typing import T_State  # noqa: TC002 - driver resolves annotations.

from ironsbot.integrations.onebot.prompt_sessions import (
    QUEUED_CONVERSATION_TOKEN_STATE_KEY,
    PromptSessionManager,
    _QueuedConversation,
)
from ironsbot.integrations.onebot.queued_conversation_input import (
    capture_queued_conversation_input,
)

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.queued_conversation_input import (
        PromptSessionGetter,
    )


def matches_active_queued_conversation(
    prompt_sessions: PromptSessionManager,
    event: Event,
    state: T_State,
) -> bool:
    """Attach the active menu context that owns this input event."""

    context = prompt_sessions.matching_queued_conversation(event)
    if context is None:
        return False
    state[QUEUED_CONVERSATION_TOKEN_STATE_KEY] = context.token
    return True


def matches_active_queued_conversation_exit(
    prompt_sessions: PromptSessionManager,
    event: Event,
    state: T_State,
) -> bool:
    return (
        event.get_plaintext().strip() == "0"
        and matches_active_queued_conversation(prompt_sessions, event, state)
    )


async def capture_durable_queued_conversation_input(
    matcher: Matcher,
    event: Event,
    state: T_State,
    *,
    get_prompt_sessions: PromptSessionGetter,
) -> None:
    await capture_queued_conversation_input(
        matcher,
        event,
        state,
        get_prompt_sessions=get_prompt_sessions,
        dispatch_handlers=dispatch_queued_conversation_handlers,
    )


def dispatch_queued_conversation_handlers(
    matcher: Matcher,
    context: _QueuedConversation,
) -> None:
    """Append this input's menu handlers after stable router admission."""

    for handler in context.handlers:
        matcher.remain_handlers.append(
            handler
            if isinstance(handler, Dependent)
            else Dependent[Any].parse(
                call=handler,
                allow_types=matcher.__class__.HANDLER_PARAM_TYPES,
            )
        )
