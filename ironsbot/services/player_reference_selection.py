# SPDX-License-Identifier: MIT
"""Resolve a visible player reference before running a typed business action."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.selection import format_selection_menu
from ironsbot.services.portable_query_sessions import PortableMenuSpec

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.player_references import PlayerReferenceChoice
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableReply
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver

PlayerReferenceAction = Callable[
    [int, "MessageInputContext"], Awaitable["OutboundMessage | PortableReply"]
]


async def select_player_reference(  # noqa: PLR0913 - explicit session and domain ports
    reference: str,
    context: MessageInputContext,
    resolver: PlayerIdResolver,
    sessions: PortableQuerySessions,
    execute: PlayerReferenceAction,
    *,
    title: str,
) -> OutboundMessage | PortableReply:
    choices = resolver.reference_choices(
        reference,
        context.message.actor,
        context.message.conversation,
    )
    if not choices:
        return OutboundMessage.from_text("未找到该米米号或已开放的玩家别名。")
    if len(choices) == 1:
        return await execute(choices[0].player_id, context)

    async def select(
        choice: PlayerReferenceChoice, context: MessageInputContext,
    ) -> OutboundMessage | PortableReply:
        current = resolver.reference_choices(
            reference,
            context.message.actor,
            context.message.conversation,
        )
        if choice not in current:
            return OutboundMessage.from_text("该玩家别名已不可用，请重新发送原命令。")
        return await execute(choice.player_id, context)

    return sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=choices,
            select=select,
            prompt=OutboundMessage.from_text(
                format_selection_menu(
                    title=title,
                    items=tuple(
                        f"{choice.label}（{choice.player_id}）" for choice in choices
                    ),
                )
            ),
            labels=tuple(choice.label for choice in choices),
        ),
    )
