# SPDX-License-Identifier: GPL-3.0-or-later

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.plugins.onebot.seer.query.commands.player_target import (
    event_player_reference_lookup,
    resolve_player_target,
)
from ironsbot.services.identity.player_accounts import (
    PlayerAccount,
    PlayerAccountRegistry,
)
from tests.helpers.onebot_events import group_message_event

PLAYER_ID = 105_023_264


def _group_conversation(group_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


def _binding_for(actor: ActorRef) -> int | None:
    assert actor.platform is Platform.ONEBOT
    return {"456": PLAYER_ID}.get(actor.id)


def _reference_lookup(reference: str, _conversation: object) -> int | None:
    return int(reference) if reference.isdecimal() else None


def test_player_target_uses_one_current_message_member_mention() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("收集"), MessageSegment.at(456)])
    )

    target = resolve_player_target(
        event,
        player_reference=None,
        reference_lookup=_reference_lookup,
        binding_for_user=_binding_for,
    )

    assert target.player_id == PLAYER_ID
    assert not target.offer_binding
    assert target.error is None


def test_player_target_uses_member_mention_sent_after_a_quote() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("收集"), MessageSegment.at(456)]),
        reply_sender_user_id=789,
    )

    target = resolve_player_target(
        event,
        player_reference=None,
        reference_lookup=_reference_lookup,
        binding_for_user=_binding_for,
    )

    assert target.player_id == PLAYER_ID
    assert not target.offer_binding
    assert target.error is None


def test_player_target_member_lookup_does_not_offer_to_bind_another_person() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("群星牌"), MessageSegment.at(456)])
    )

    target = resolve_player_target(
        event,
        player_reference=None,
        reference_lookup=_reference_lookup,
        binding_for_user=_binding_for,
    )

    assert not target.offer_binding


def test_player_target_rejects_ambiguous_member_target_forms() -> None:
    two_members = group_message_event(
        message=Message(
            [
                MessageSegment.text("巅峰"),
                MessageSegment.at(456),
                MessageSegment.at(789),
            ]
        )
    )
    member_and_number = group_message_event(
        message=Message([MessageSegment.text("收集712345678"), MessageSegment.at(456)])
    )

    multiple = resolve_player_target(
        two_members,
        player_reference=None,
        reference_lookup=_reference_lookup,
        binding_for_user=_binding_for,
    )
    mixed = resolve_player_target(
        member_and_number,
        player_reference="105023264",
        reference_lookup=_reference_lookup,
        binding_for_user=_binding_for,
    )

    assert multiple.error == "请一次只 @ 一名成员查询其已绑定的米米号。"
    assert mixed.error == "米米号或玩家别名和 @成员 不能同时使用，请保留其中一种。"


def test_player_target_reports_an_unbound_mentioned_member() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("米米号"), MessageSegment.at(789)])
    )

    target = resolve_player_target(
        event,
        player_reference=None,
        reference_lookup=_reference_lookup,
        binding_for_user=_binding_for,
    )

    assert target.player_id is None
    assert target.error == "该成员尚未绑定米米号。"


def test_player_target_can_require_an_explicit_reference() -> None:
    target = resolve_player_target(
        group_message_event("绑定米米号"),
        player_reference=None,
        reference_lookup=_reference_lookup,
        binding_for_user=_binding_for,
        allow_default_binding=False,
    )

    assert target.player_id is None
    assert target.error == "请填写米米号、已开放的玩家别名，或直接 @ 一名已绑定成员。"


def test_player_target_resolves_a_group_scoped_alias_once() -> None:
    private_group_id = 987654321
    accounts = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=PLAYER_ID,
                name="sample_player",
                aliases=("示例玩家",),
                password=None,
                public=False,
            ),
        ),
        private_alias_groups={
            _group_conversation(private_group_id): ("sample_player",),
        },
    )
    event = group_message_event("米米号示例玩家", group_id=private_group_id)

    target = resolve_player_target(
        event,
        player_reference="示例玩家",
        reference_lookup=event_player_reference_lookup(accounts),
        binding_for_user=_binding_for,
    )

    assert target.player_id == PLAYER_ID
    assert target.offer_binding
    assert target.error is None


def test_event_player_reference_lookup_respects_scoped_aliases() -> None:
    private_group_id = 987654321
    accounts = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=PLAYER_ID,
                name="sample_player",
                aliases=("示例玩家",),
                password=None,
                public=False,
            ),
        ),
        private_alias_groups={
            _group_conversation(private_group_id): ("sample_player",),
        },
    )

    lookup = event_player_reference_lookup(accounts)
    assert (
        lookup(
            "示例玩家",
            ConversationRef(Platform.ONEBOT, "group", str(private_group_id)),
        )
        == PLAYER_ID
    )
    other_group_lookup = event_player_reference_lookup(accounts)
    assert (
        other_group_lookup(
            "示例玩家",
            ConversationRef(Platform.ONEBOT, "group", "123456789"),
        )
        is None
    )
    private_lookup = event_player_reference_lookup(accounts)
    assert (
        private_lookup(
            str(PLAYER_ID),
            ConversationRef(Platform.ONEBOT, "private", "123"),
        )
        == PLAYER_ID
    )


def test_scoped_player_alias_stays_on_its_platform() -> None:
    conversation = _group_conversation(987654321)
    accounts = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=PLAYER_ID,
                name="sample_player",
                aliases=("示例玩家",),
                password=None,
                public=False,
            ),
        ),
        private_alias_groups={conversation: ("sample_player",)},
    )

    assert (
        accounts.resolve_player_id("示例玩家", conversation=conversation)
        == PLAYER_ID
    )
    assert (
        accounts.resolve_player_id(
            "示例玩家",
            conversation=ConversationRef(
                Platform.QQ_OFFICIAL,
                "group",
                conversation.id,
            ),
        )
        is None
    )
