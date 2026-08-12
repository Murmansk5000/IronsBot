# SPDX-License-Identifier: MIT
"""Session-bound ingress for queued prompt conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.adapters import Event  # noqa: TC002 - Rule resolves annotations
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher, current_bot, current_event
from nonebot.rule import Rule

from ironsbot.runtime.prompt_sessions import QUEUED_CONVERSATION_TOKEN_STATE_KEY

if TYPE_CHECKING:
    from nonebot.typing import T_State

    from ironsbot.runtime.prompt_sessions import _QueuedConversation

QUEUED_CONVERSATION_FALLBACK_STATE_KEY = (
    "_ironsbot_queued_conversation_fallback"
)
QUEUED_CONVERSATION_FALLBACK_GENERATION_STATE_KEY = (
    "_ironsbot_queued_conversation_fallback_generation"
)
QUEUED_CONVERSATION_FALLBACK_PRIORITY = -27
_RUNTIME_CONTEXT_STATE_KEY = "_ironsbot_runtime_context_token"


async def create_queued_conversation_fallback(
    matcher: Matcher,
    context: _QueuedConversation,
    *,
    handler: Any,
    runtime_context_key: str = _RUNTIME_CONTEXT_STATE_KEY,
    priority: int = QUEUED_CONVERSATION_FALLBACK_PRIORITY,
) -> None:
    """Create the next session-bound matcher for one menu input."""

    bot = current_bot.get()
    event = current_event.get()
    permission = await matcher.update_permission(bot, event)
    context.fallback_generation += 1
    generation = context.fallback_generation

    def matches_current_generation(next_event: Event) -> bool:
        return (
            context.active
            and context.fallback_generation == generation
            and context.matches(next_event)
        )

    default_state: T_State = {
        QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token,
        QUEUED_CONVERSATION_FALLBACK_STATE_KEY: True,
        QUEUED_CONVERSATION_FALLBACK_GENERATION_STATE_KEY: generation,
    }
    if runtime_token := matcher.state.get(runtime_context_key):
        default_state[runtime_context_key] = runtime_token
    matcher.__class__.new(
        "message",
        Rule(matches_current_generation),
        permission,
        [handler],
        temp=True,
        priority=priority,
        block=True,
        source=matcher.__class__._source,
        expire_time=bot.config.session_expire_timeout,
        default_state=default_state,
        default_type_updater=matcher.__class__._default_type_updater,
        default_permission_updater=matcher.__class__._default_permission_updater,
    )


async def refresh_queued_conversation_fallback(  # noqa: PLR0913
    matcher: Matcher,
    event: Event,
    state: T_State,
    context: _QueuedConversation | None,
    *,
    handler: Any,
    runtime_context_key: str = _RUNTIME_CONTEXT_STATE_KEY,
    priority: int = QUEUED_CONVERSATION_FALLBACK_PRIORITY,
) -> None:
    """Validate one fallback generation and install its successor immediately."""

    generation = state.get(QUEUED_CONVERSATION_FALLBACK_GENERATION_STATE_KEY)
    if (
        context is None
        or not isinstance(generation, int)
        or generation != context.fallback_generation
    ):
        raise FinishedException
    logger.info(
        "queued conversation session fallback accepted: namespace={} "
        "session={} user={} message_id={} generation={}",
        context.namespace,
        context.event_session_id,
        getattr(event, "user_id", None),
        getattr(event, "message_id", None),
        generation,
    )
    await create_queued_conversation_fallback(
        matcher,
        context,
        handler=handler,
        runtime_context_key=runtime_context_key,
        priority=priority,
    )
