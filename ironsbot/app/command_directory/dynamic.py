# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.runtime.commands import CommandDescriptor

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings


def ai_intent_commands(config: Settings) -> tuple[CommandDescriptor, ...]:
    if not config.ai.api_key.strip() or not config.ai.intent_actions_enabled:
        return ()
    return tuple(
        CommandDescriptor(
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
