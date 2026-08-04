from __future__ import annotations

from ironsbot.core.message_input import MessageInputContext, MessageInputKind
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)


def test_message_input_context_classifies_platform_neutral_direct_mentions() -> None:
    context = MessageInputContext(
        IncomingMessageRef(
            id="message-1",
            actor=ActorRef(Platform.QQ_OFFICIAL, "open-id"),
            conversation=ConversationRef(Platform.QQ_OFFICIAL, "group", "group-id"),
            text="查询",
            direct_mentions=(ActorRef(Platform.QQ_OFFICIAL, "target-open-id"),),
        ),
        mentions_bot=False,
    )

    assert context.kind is MessageInputKind.MEMBER_MENTION
    assert context.member_mentions[0].id == "target-open-id"


def test_reply_precedes_bot_mention_for_all_platforms() -> None:
    context = MessageInputContext(
        IncomingMessageRef(
            id="message-1",
            actor=ActorRef(Platform.ONEBOT, "123"),
            conversation=ConversationRef(Platform.ONEBOT, "group", "456"),
            text="帮助",
            reply_to_id="message-0",
        ),
        mentions_bot=True,
    )

    assert context.kind is MessageInputKind.REPLY
