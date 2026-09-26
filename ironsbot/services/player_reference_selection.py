# SPDX-License-Identifier: MIT
"""Resolve a visible player reference before running a typed business action."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.selection import format_selection_menu
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.player_references import PlayerReferenceChoice
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver

PlayerReferenceAction = Callable[
    [int, "MessageInputContext"], Awaitable["OutboundMessage | PortableReply"]
]


async def select_player_target(  # noqa: PLR0913 - explicit session and domain ports
    reference: str | None,
    context: MessageInputContext,
    resolver: PlayerIdResolver,
    sessions: PortableQuerySessions,
    execute: PlayerReferenceAction,
    *,
    title: str,
) -> PortableReply:
    """Select an explicit reference or resolve a direct mention/default binding."""
    reference = (reference or "").strip()
    if reference and not context.has_member_mentions:
        result = await select_player_reference(
            reference,
            context,
            resolver,
            sessions,
            execute,
            title=title,
            enforce_query_access=True,
        )
    else:
        resolution = resolver.resolve(context, reference)
        if resolution.error is not None:
            return PortableReply(OutboundMessage.from_text(resolution.error))
        if resolution.player_id is None:
            return PortableReply(
                OutboundMessage.from_text(unbound_player_shortcut_message())
            )
        result = await execute(resolution.player_id, context)
    return result if isinstance(result, PortableReply) else PortableReply(result)


async def select_player_reference(  # noqa: C901, PLR0913 - selection and access checks
    reference: str,
    context: MessageInputContext,
    resolver: PlayerIdResolver,
    sessions: PortableQuerySessions,
    execute: PlayerReferenceAction,
    *,
    title: str,
    enforce_query_access: bool = False,
) -> OutboundMessage | PortableReply:
    source = resolver.reference_source(reference)
    if enforce_query_access:
        error = resolver.query_access_error(context.message.actor, None, source)
        if error is not None:
            return OutboundMessage.from_text(error)
    choices = resolver.reference_choices(
        reference,
        context.message.actor,
        context.message.conversation,
    )
    if not choices:
        return OutboundMessage.from_text("未找到该米米号或已开放的玩家别名。")
    if len(choices) == 1:
        if enforce_query_access:
            error = resolver.query_access_error(
                context.message.actor, choices[0].player_id, source
            )
            if error is not None:
                return OutboundMessage.from_text(error)
        return await execute(choices[0].player_id, context)

    async def select(
        choice: PlayerReferenceChoice,
        context: MessageInputContext,
    ) -> OutboundMessage | PortableReply:
        current = resolver.reference_choices(
            reference,
            context.message.actor,
            context.message.conversation,
        )
        if choice not in current:
            return OutboundMessage.from_text("该玩家别名已不可用，请重新发送原命令。")
        if enforce_query_access:
            error = resolver.query_access_error(
                context.message.actor, choice.player_id, source
            )
            if error is not None:
                return OutboundMessage.from_text(error)
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
