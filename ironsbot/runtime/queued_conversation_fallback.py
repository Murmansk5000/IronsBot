# SPDX-License-Identifier: MIT
"""Session-bound fallback ingress for queued prompt conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.matcher import Matcher, current_bot, current_event
from nonebot.rule import Rule

from ironsbot.runtime.prompt_sessions import QUEUED_CONVERSATION_TOKEN_STATE_KEY

if TYPE_CHECKING:
    from nonebot.typing import T_State

    from ironsbot.runtime.prompt_sessions import _QueuedConversation

QUEUED_CONVERSATION_FALLBACK_STATE_KEY = (
    "_ironsbot_queued_conversation_fallback"
)


async def create_queued_conversation_fallback(
    matcher: Matcher,
    context: _QueuedConversation,
    *,
    handler: Any,
    runtime_context_key: str,
) -> None:
    """Create a session-bound ingress behind the durable queued-menu router.

    The durable router normally owns the input. This fallback retains the
    originating matcher runtime context for adapters that lose the durable
    router's state. The shared input claim prevents duplicate execution.
    """

    bot = current_bot.get()
    event = current_event.get()
    permission = await matcher.update_permission(bot, event)
    default_state: T_State = {
        QUEUED_CONVERSATION_TOKEN_STATE_KEY: context.token,
        QUEUED_CONVERSATION_FALLBACK_STATE_KEY: True,
    }
    if runtime_token := matcher.state.get(runtime_context_key):
        default_state[runtime_context_key] = runtime_token
    matcher.__class__.new(
        "message",
        Rule(context.matches),
        permission,
        [handler],
        temp=True,
        # The durable router runs first. This only catches an adapter state
        # restoration failure for the originating menu.
        priority=-19,
        block=True,
        source=matcher.__class__._source,
        expire_time=bot.config.session_expire_timeout,
        default_state=default_state,
        default_type_updater=matcher.__class__._default_type_updater,
        default_permission_updater=matcher.__class__._default_permission_updater,
    )
