# SPDX-License-Identifier: MIT
"""Owner-only binding confirmation shared by independent player shortcuts."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.portable_reply import PortableReply

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.seer.player_service import PlayerService


async def confirm_shortcut_binding(
    service: PlayerService,
    sessions: PortableQuerySessions,
    player_id: int,
    context: MessageInputContext,
    query: Callable[[int, MessageInputContext], Awaitable[PortableReply]],
) -> PortableReply:
    if (
        context.has_member_mentions
        or not context.offer_player_binding
        or not service.should_offer_binding(context.message.actor)
    ):
        return await query(player_id, context)

    async def confirm(
        choice: Literal["confirm", "skip"], selected: MessageInputContext
    ) -> PortableReply:
        if choice == "confirm":
            status = (
                service.bind_shortcut_target(selected.message.actor, player_id)
                if service.should_offer_binding(selected.message.actor)
                else "当前绑定状态已变化，请重新发送查询指令。"
            )
        else:
            service.decline_binding_offer(selected.message.actor)
            status = ""
        reply = await query(player_id, selected)
        if not status:
            return reply
        return replace(
            reply,
            message=replace(
                reply.message, parts=(TextPart(status + "\n\n"), *reply.message.parts)
            ),
        )

    return PortableReply(
        sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=("confirm", "skip"),
                choice_keys=("confirm", "skip"),
                labels=("确认绑定", "跳过绑定"),
                select=confirm,
                text_inputs=(
                    frozenset({"是", "y", "yes"}),
                    frozenset({"否", "n", "no"}),
                ),
                prompt=OutboundMessage.from_text(
                    service.shortcut_binding_offer(player_id)
                ),
                exit_message="已退出查询。",
            ),
        )
    )
