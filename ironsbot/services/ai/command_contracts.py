# SPDX-License-Identifier: MIT
"""Platform-neutral command contracts for AI chat and intent actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandContract,
    commands_from_rows,
)

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings


def ai_chat_command_contracts(*, enabled: bool) -> tuple[CommandContract, ...]:
    """Describe AI chat inputs only when an AI provider is configured."""

    if not enabled:
        return ()
    return (
        *commands_from_rows(
            "ai_chat",
            "群聊",
            "ai_chat",
            (
                (
                    "ai_chat.group",
                    ("@机器人 <问题>",),
                    "向 AI 聊天提问",
                    {"access": (CommandAccess(scope="group"),)},
                ),
            ),
        ),
        *commands_from_rows(
            "ai_chat",
            "私聊",
            "ai_chat",
            (
                (
                    "ai_chat.private",
                    ("<问题>",),
                    "直接向 AI 聊天提问",
                    {"access": (CommandAccess(scope="private"),)},
                ),
            ),
        ),
    )


def ai_intent_command_contracts(
    config: Settings,
) -> tuple[CommandContract, ...]:
    """Describe configured automatic AI intent actions."""

    if not config.ai.ai_enabled or not config.ai.intent_actions_enabled:
        return ()
    return tuple(
        CommandContract(
            id=f"ai_intent.{action_id}",
            plugin_id="ai_intent",
            section="关键词意图",
            examples=tuple(action.keywords),
            description="机器人识别到相应意图后自动回复",
            features_any=(action.feature,),
            interaction="automatic",
        )
        for action_id, action in config.ai.intent_actions.items()
        if action.enabled and action.keywords
    )
