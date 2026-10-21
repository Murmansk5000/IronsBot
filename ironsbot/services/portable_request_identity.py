# SPDX-License-Identifier: MIT
"""Resolve command admission identities before their domain operation runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    normalized_text_target,
)
from ironsbot.services.seer.query_commands import pet_query_input
from ironsbot.services.seer.rank_list_parsing import parse_rank_player_target_command

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.action_categories import RequestCategory
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableReply


async def execute_ai_fallback(
    sessions: PortableQuerySessions,
    context: MessageInputContext,
    prompt: str,
    operation: Callable[[], Awaitable[PortableReply | None]],
) -> PortableReply | None:
    target = normalized_text_target(prompt)
    if target is None:
        return await operation()
    return await sessions.interactions.execute_request(
        SemanticRequest(
            ActionDefinition("ai_chat", "AI 查询"),
            target,
            SemanticRequestSource.AI_INTENT,
        ),
        context,
        operation,
    )


def direct_command_request(
    command_id: str,
    command: str,
    context: MessageInputContext,
    *,
    category: RequestCategory | None = None,
) -> SemanticRequest | None:
    if command_id in {
        "seer.player.query",
        "seer.player.default",
        "private_player_lineup",
        "seer.lucky_skin_window.query",
    }:
        # Resolve aliases/default bindings before reserving the real player.
        return None
    if command_id in {"rank.global_collection", "rank.global_peak"}:
        player = parse_rank_player_target_command(command)
        if player is not None and (
            player.player_reference or context.has_member_mentions
        ):
            # The domain operation admits the resolved player, not the alias.
            return None
    target_text = (
        pet_query_input().parse_argument(command)
        if command_id == "seer.pet.query"
        else command
    )
    target = normalized_text_target(target_text or "")
    if target is None:
        return None
    return SemanticRequest(
        action=ActionDefinition(id=command_id, label=command_id, category=category),
        target=target,
        source=SemanticRequestSource.DIRECT,
    )
