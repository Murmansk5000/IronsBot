# SPDX-License-Identifier: MIT
"""Shared fallback operations; transports only supply event/source context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_reply import PortableReply

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.messaging import AiIntentAction
    from ironsbot.services.ai.actions import AiIntentActionExecutor
    from ironsbot.services.ai.input_routing import AiInputRoutingService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.messaging.addressed_input import AddressedInputHintService


async def resolve_intent(
    service: AiService,
    routing: AiInputRoutingService,
    context: MessageInputContext,
    prompt: str,
    *,
    source_context: str,
) -> AiIntentAction | None:
    if not routing.decide(
        context, command_context_from_input(context), normalized_text=prompt
    ).try_intent:
        return None
    return await service.classify_intent(
        prompt,
        actor=context.message.actor,
        conversation=context.message.conversation,
        source_context=source_context,
    )


async def execute_intent(
    executor: AiIntentActionExecutor,
    action: AiIntentAction,
    prompt: str,
    *,
    source_context: str | None,
) -> PortableReply | None:
    messages = await executor.execute(action, prompt, source_context=source_context)
    return (
        PortableReply(messages[0], additional_messages=messages[1:])
        if messages
        else None
    )


def addressed_hint(
    hints: AddressedInputHintService,
    routing: AiInputRoutingService,
    context: MessageInputContext,
) -> PortableReply | None:
    command_context = command_context_from_input(context)
    if not routing.decide(context, command_context).offer_addressed_hint:
        return None
    if not hints.admit(context):
        return None
    return PortableReply(OutboundMessage.from_text(hints.reply(command_context)))
