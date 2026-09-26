# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-neutral resolution of Seer player-ID command targets."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ironsbot.core.platform import ActorRef
from ironsbot.core.player_references import PlayerReferenceChoice

if TYPE_CHECKING:
    from ironsbot.config.models.seer import PlayerBindingConfig
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ConversationRef
    from ironsbot.core.player_references import (
        PlayerReferenceLookup,
        PlayerReferenceSearch,
    )


@dataclass(frozen=True, slots=True)
class PlayerIdResolution:
    """One resolved player target or the user-facing reason it is unavailable."""

    player_id: int | None
    offer_binding: bool
    error: str | None = None
    source: Literal["numeric", "alias", "member", "default"] | None = None


PlayerBindingLookup = Callable[[ActorRef], int | None]
ActorPrivilegeLookup = Callable[[ActorRef], bool]
ActorIdentityMatch = Callable[[ActorRef, ActorRef], bool]
PlayerTargetSource = Literal["numeric", "alias", "member", "default", "shared_menu"]
PLAYER_ID_RESOLVER_REQUIRED_ERROR = "player ID resolver is not configured"


class PlayerIdResolver:
    """Resolve one player reference, one direct mention, or the caller binding."""

    def __init__(  # noqa: PLR0913 - resolver owns all query access inputs
        self,
        reference_lookup: PlayerReferenceLookup,
        binding_lookup: PlayerBindingLookup,
        *,
        privileged_reference_lookup: PlayerReferenceLookup | None = None,
        is_privileged_actor: ActorPrivilegeLookup | None = None,
        reference_search: PlayerReferenceSearch | None = None,
        binding_config: PlayerBindingConfig | None = None,
        superuser_actors: Callable[[], Iterable[ActorRef]] | None = None,
        same_actor: ActorIdentityMatch | None = None,
    ) -> None:
        self._reference_lookup = reference_lookup
        self._binding_lookup = binding_lookup
        self._privileged_reference_lookup = privileged_reference_lookup
        self._is_privileged_actor = is_privileged_actor or (lambda _actor: False)
        self._reference_search = reference_search
        self._binding_config = binding_config
        self._superuser_actors = superuser_actors or (lambda: ())
        self._same_actor = same_actor or (lambda left, right: left == right)

    def query_access_error(
        self, actor: ActorRef, player_id: int | None, source: PlayerTargetSource
    ) -> str | None:
        """Check provenance before any player query or cached result is requested."""
        config = self._binding_config
        if config is None:
            return None
        if self._binding_lookup(actor) is None:
            allowed = {
                "numeric": config.allow_unbound_numeric_queries,
                "alias": config.allow_unbound_alias_queries,
                "member": config.allow_unbound_member_queries,
                "default": False,
                "shared_menu": config.allow_unbound_alias_queries,
            }[source]
            if not allowed:
                return "请先绑定默认米米号，再使用该快捷查询。"
        if (
            player_id is not None
            and source != "numeric"
            and not config.allow_others_superuser_bound_shortcuts
        ):
            owners = tuple(
                owner
                for owner in self._superuser_actors()
                if self._binding_lookup(owner) == player_id
            )
            if owners and not any(self._same_actor(actor, owner) for owner in owners):
                return "该米米号不支持快捷查询，请使用完整数字米米号。"
        return None

    def reference_source(self, reference: str) -> Literal["numeric", "alias"]:
        return "numeric" if reference.strip().isdecimal() else "alias"

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
            return self.resolve_reference(
                normalized_reference,
                context.message.actor,
                context.message.conversation,
            )
        if allow_default_binding:
            player_id = self._binding_lookup(context.message.actor)
            return PlayerIdResolution(
                player_id,
                offer_binding=False,
                error=(
                    self.query_access_error(context.message.actor, player_id, "default")
                    if player_id is not None
                    else None
                ),
                source="default",
            )
        return PlayerIdResolution(
            None,
            offer_binding=False,
            error="请填写米米号、已开放的玩家别名，或直接 @ 一名已绑定成员。",
        )

    def resolve_reference(
        self,
        reference: str,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> PlayerIdResolution:
        """Resolve the game account independently of the message's recipient."""
        player_id = self._lookup_reference(reference, actor, conversation)
        source = self.reference_source(reference)
        return PlayerIdResolution(
            player_id,
            offer_binding=player_id is not None,
            error=(
                self.query_access_error(actor, player_id, source)
                or ("未找到该米米号或已开放的玩家别名。" if player_id is None else None)
            ),
            source=source,
        )

    def has_known_reference(
        self,
        reference: str,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> bool:
        """Return whether an explicit non-numeric player reference is visible.

        CommandCatalog uses this narrow query to recognize a configured alias
        without duplicating alias ownership or evaluating default bindings and
        direct member mentions, which are message-level concerns.
        """

        return self._lookup_reference(reference, actor, conversation) is not None

    def reference_choices(
        self,
        reference: str,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> tuple[PlayerReferenceChoice, ...]:
        """Exact references take precedence over visible substring candidates."""
        player_id = self._lookup_reference(reference, actor, conversation)
        if player_id is not None:
            return (PlayerReferenceChoice(player_id, reference.strip()),)
        if self._reference_search is None:
            return ()
        return self._reference_search(reference, actor, conversation)

    def has_reference_choices(
        self,
        reference: str,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> bool:
        return bool(self.reference_choices(reference, actor, conversation))

    def _lookup_reference(
        self,
        reference: str,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> int | None:
        lookup = (
            self._privileged_reference_lookup
            if self._privileged_reference_lookup is not None
            and self._is_privileged_actor(actor)
            else self._reference_lookup
        )
        return lookup(reference.strip(), conversation)

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
        access_error = self.query_access_error(context.message.actor, None, "member")
        if access_error is not None:
            return PlayerIdResolution(None, offer_binding=False, error=access_error)
        player_id = self._binding_lookup(context.member_mentions[0])
        if player_id is None:
            return PlayerIdResolution(
                None,
                offer_binding=False,
                error="该成员尚未绑定米米号。",
            )
        return PlayerIdResolution(
            player_id,
            offer_binding=False,
            error=self.query_access_error(context.message.actor, player_id, "member"),
            source="member",
        )
