# SPDX-License-Identifier: MIT
"""Shared AI-chat execution after platform-independent input admission."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.ai.service import AiService


async def execute_chat(
    service: AiService,
    context: MessageInputContext,
    prompt: str,
    *,
    source_context: str,
) -> str | None:
    prompt = prompt.strip()
    if not prompt:
        return "你想聊什么？可以直接写问题。"
    return await service.chat_reply(
        actor=context.message.actor,
        conversation=context.message.conversation,
        prompt=prompt,
        source_context=source_context,
    )
