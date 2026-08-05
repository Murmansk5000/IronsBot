# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-neutral resolution of Seer player-ID command targets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ConversationRef
    from ironsbot.core.player_references import PlayerReferenceLookup


@dataclass(frozen=True, slots=True)
class PlayerIdResolution:
    """One resolved player target or the user-facing reason it is unavailable."""

    player_id: int | None
    offer_binding: bool
    error: str | None = None


PlayerBindingLookup = Callable[[ActorRef], int | None]
PLAYER_ID_RESOLVER_REQUIRED_ERROR = "player ID resolver is not configured"


class PlayerIdResolver:
    """Resolve one player reference, one direct mention, or the caller binding."""

    def __init__(
        self,
        reference_lookup: PlayerReferenceLookup,
        binding_lookup: PlayerBindingLookup,
    ) -> None:
        self._reference_lookup = reference_lookup
        self._binding_lookup = binding_lookup

    def resolve(
        self,
        context: MessageInputContext,
        reference: str | None,
        *,
        allow_default_binding: bool = True,
    ) -> PlayerIdResolution:
        """Resolve current-message input without considering quoted mentions."""

        normalized_reference = (reference or "").strip()
        if context.has_member_mentions:
            return self._resolve_member_mentions(context, normalized_reference)
        if normalized_reference:
            player_id = self._reference_lookup(
                normalized_reference,
                context.message.conversation,
            )
            return PlayerIdResolution(
                player_id,
                offer_binding=player_id is not None,
                error=(
                    "未找到该米米号或已开放的玩家别名。"
                    if player_id is None
                    else None
                ),
            )
        if allow_default_binding:
            return PlayerIdResolution(
                self._binding_lookup(context.message.actor),
                offer_binding=False,
            )
        return PlayerIdResolution(
            None,
            offer_binding=False,
            error="请填写米米号、已开放的玩家别名，或直接 @ 一名已绑定成员。",
        )

    def has_known_reference(
        self,
        reference: str,
        conversation: ConversationRef,
    ) -> bool:
        """Return whether an explicit non-numeric player reference is visible.

        CommandCatalog uses this narrow query to recognize a configured alias
        without duplicating alias ownership or evaluating default bindings and
        direct member mentions, which are message-level concerns.
        """

        return self._reference_lookup(reference, conversation) is not None

    def _resolve_member_mentions(
        self,
        context: MessageInputContext,
        normalized_reference: str,
    ) -> PlayerIdResolution:
        if context.message.conversation.kind != "group":
            return PlayerIdResolution(
                None,
                offer_binding=False,
                error="私聊不能使用 @成员 查询米米号。",
            )
        if normalized_reference:
            return PlayerIdResolution(
                None,
                offer_binding=False,
                error="米米号或玩家别名和 @成员 不能同时使用，请保留其中一种。",
            )
        if len(context.member_mentions) != 1:
            return PlayerIdResolution(
                None,
                offer_binding=False,
                error="请一次只 @ 一名成员查询其已绑定的米米号。",
            )
        player_id = self._binding_lookup(context.member_mentions[0])
        if player_id is None:
            return PlayerIdResolution(
                None,
                offer_binding=False,
                error="该成员尚未绑定米米号。",
            )
        return PlayerIdResolution(player_id, offer_binding=False)
