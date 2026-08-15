# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve player-query targets from references, bindings, or one @ member."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.onebot_context import event_group_id
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot.adapters import Event

    from ironsbot.config.player_accounts import PlayerAccountRegistry


@dataclass(frozen=True, slots=True)
class PlayerTargetResolution:
    player_id: int | None
    offer_binding: bool
    error: str | None = None


def resolve_event_player_reference(
    accounts: PlayerAccountRegistry,
    event: Event,
    reference: object,
    *,
    allow_private: bool = False,
) -> int | None:
    """Resolve one numeric or configured player reference in event scope."""

    return accounts.resolve_player_id(
        reference,
        group_id=event_group_id(event) if isinstance(event, MessageEvent) else None,
        allow_private=allow_private,
    )


def resolve_player_target(  # noqa: PLR0911
    event: MessageEvent,
    *,
    numeric_player_id: int | None,
    binding_for_user: Callable[[int], int | None],
) -> PlayerTargetResolution:
    """Use exactly one current-message @ target, never a quoted message body."""

    context = message_input_context(event)
    if context.has_member_mentions:
        if not isinstance(event, GroupMessageEvent):
            return PlayerTargetResolution(
                None,
                offer_binding=False,
                error="私聊不能使用 @成员 查询米米号。",
            )
        if numeric_player_id is not None:
            return PlayerTargetResolution(
                None,
                offer_binding=False,
                error="米米号或玩家别名和 @成员 不能同时使用，请保留其中一种。",
            )
        if len(context.member_user_ids) != 1:
            return PlayerTargetResolution(
                None,
                offer_binding=False,
                error="请一次只 @ 一名成员查询其已绑定的米米号。",
            )
        if binding_for_user(event.user_id) is None:
            return PlayerTargetResolution(
                None,
                offer_binding=False,
                error=unbound_player_shortcut_message(),
            )
        player_id = binding_for_user(context.member_user_ids[0])
        if player_id is None:
            return PlayerTargetResolution(
                None,
                offer_binding=False,
                error="该成员尚未绑定米米号。",
            )
        return PlayerTargetResolution(player_id, offer_binding=False)

    if numeric_player_id is not None:
        return PlayerTargetResolution(numeric_player_id, offer_binding=True)
    return PlayerTargetResolution(
        binding_for_user(event.user_id),
        offer_binding=False,
    )
