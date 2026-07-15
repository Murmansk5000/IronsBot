# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Final

from nonebot.log import logger

from ironsbot.services.ai.client import call_ai_chat
from ironsbot.services.ai.config import get_ai_key
from ironsbot.services.ai.constants import EMPTY_REPLY, REQUEST_FAILED_REPLY
from ironsbot.services.ai.intent import (
    build_intent_prompt,
    contains_any_keyword,
    excluded_by_command,
    excluded_by_context,
    format_action_template,
    get_ai_intent_config,
    get_configured_actions,
    is_action_allowed,
    is_ai_intent_allowed,
    passes_action_prefilter,
    reply_is_yes,
)
from ironsbot.services.ai.source_context import build_ai_notice_source_context

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent

    from ironsbot.config.models.ai import AiIntentAction

TEAM_ACTIONS: Final[frozenset[str]] = frozenset({"team_recommend", "team_resource"})


def is_team_action(action: AiIntentAction) -> bool:
    return action.action in TEAM_ACTIONS


async def classify_ai_intent_action(event: MessageEvent) -> AiIntentAction | None:
    if not get_ai_intent_config().intent_actions_enabled:
        return None

    text = event.get_plaintext().strip()
    if not text or not get_ai_key() or not is_ai_intent_allowed(event):
        return None

    for action in get_configured_actions():
        if (
            not action.enabled
            or not is_action_allowed(event, action)
            or not contains_any_keyword(text, action.keywords)
            or not passes_action_prefilter(text, action)
            or excluded_by_command(text, action)
            or excluded_by_context(text, action)
        ):
            continue

        try:
            reply = await call_ai_chat(
                build_intent_prompt(action, text),
                [],
                source_context=await build_ai_notice_source_context(event, text),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AI intent action failed to classify {action.id}: {e}")
            return None

        if reply in {REQUEST_FAILED_REPLY, EMPTY_REPLY}:
            return None

        logger.info(
            f"AI intent action {action.id or '<unnamed>'} classified "
            f"{event.user_id}: {reply!r}"
        )
        if reply_is_yes(reply):
            return action

    return None


async def run_ai_reply_action(
    action: AiIntentAction,
    event: MessageEvent,
) -> str | None:
    text = event.get_plaintext().strip()
    prompt = format_action_template(action, action.reply_prompt, text)
    reply = await call_ai_chat(
        prompt,
        [],
        source_context=await build_ai_notice_source_context(event, text),
    )
    if reply in {REQUEST_FAILED_REPLY, EMPTY_REPLY}:
        return None
    return reply


__all__ = [
    "TEAM_ACTIONS",
    "classify_ai_intent_action",
    "is_team_action",
    "run_ai_reply_action",
]
