# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Literal

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.player_reference_commands import player_reference_input_matcher
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver

_ALIAS_PLAYER_ID = 700
_CURRENT_PLAYER_ID = 600
_MENTIONED_PLAYER_ID = 800


def _context(
    *,
    kind: Literal["private", "group", "channel", "guild"] = "group",
    mentions: tuple[ActorRef, ...] = (),
) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.ONEBOT,
            actor=ActorRef(Platform.ONEBOT, "100"),
            conversation=ConversationRef(Platform.ONEBOT, kind, "200"),
            message_id="message-1",
            text="收集",
            direct_mentions=mentions,
        ),
        mentions_bot=False,
    )


def _resolver() -> PlayerIdResolver:
    return PlayerIdResolver(
        lambda reference, _conversation: {"alias": _ALIAS_PLAYER_ID}.get(reference),
        lambda actor: {
            "100": _CURRENT_PLAYER_ID,
            "300": _MENTIONED_PLAYER_ID,
        }.get(actor.id),
    )


def test_resolves_alias_in_the_current_conversation() -> None:
    result = _resolver().resolve(_context(), "alias")

    assert result.player_id == _ALIAS_PLAYER_ID
    assert result.offer_binding is True
    assert result.error is None


def test_privileged_actor_can_resolve_a_private_alias() -> None:
    resolver = PlayerIdResolver(
        lambda _reference, _conversation: None,
        lambda _actor: None,
        privileged_reference_lookup=lambda reference, _conversation: {
            "private": _ALIAS_PLAYER_ID
        }.get(reference),
        is_privileged_actor=lambda actor: actor.id == "100",
    )

    result = resolver.resolve(_context(), "private")

    assert result.player_id == _ALIAS_PLAYER_ID
    assert result.offer_binding is True


def test_recognizes_known_aliases_without_evaluating_message_targets() -> None:
    resolver = _resolver()
    conversation = ConversationRef(Platform.ONEBOT, "group", "200")

    actor = ActorRef(Platform.ONEBOT, "100")
    assert resolver.has_known_reference("alias", actor, conversation)
    assert not resolver.has_known_reference("unknown", actor, conversation)


def test_uses_current_actor_binding_when_no_reference_is_given() -> None:
    result = _resolver().resolve(_context(), None)

    assert result.player_id == _CURRENT_PLAYER_ID
    assert result.offer_binding is False


def test_member_mention_uses_the_mentioned_actor_binding() -> None:
    result = _resolver().resolve(
        _context(mentions=(ActorRef(Platform.ONEBOT, "300"),)),
        None,
    )

    assert result.player_id == _MENTIONED_PLAYER_ID
    assert result.offer_binding is False


def test_member_mention_rejects_a_mixed_alias_reference() -> None:
    result = _resolver().resolve(
        _context(mentions=(ActorRef(Platform.ONEBOT, "300"),)),
        "alias",
    )

    assert result.player_id is None
    assert result.error == "米米号或玩家别名和 @成员 不能同时使用，请保留其中一种。"


def test_member_actor_resolution_rejects_unbound_target() -> None:
    result = _resolver().resolve(
        _context(mentions=(ActorRef(Platform.ONEBOT, "999"),)),
        None,
    )

    assert result.player_id is None
    assert result.error == "该成员尚未绑定米米号。"


def test_member_mention_requires_group_conversation() -> None:
    result = _resolver().resolve(
        _context(
            kind="private",
            mentions=(ActorRef(Platform.ONEBOT, "300"),),
        ),
        None,
    )

    assert result.player_id is None
    assert result.error == "私聊不能使用 @成员 查询米米号。"


def test_player_reference_input_matcher_claims_only_numeric_or_known_aliases() -> None:
    matcher = player_reference_input_matcher(
        ("米米号",),
        lambda reference, _actor, _conversation: reference == "alias",
    )
    context = CommandContext(
        actor=ActorRef(Platform.ONEBOT, "100"),
        conversation=ConversationRef(Platform.ONEBOT, "private", "100"),
    )

    assert matcher("米米号", context)
    assert matcher("米米号123456", context)
    assert matcher("米米号alias", context)
    assert not matcher("米米号是多少", context)
