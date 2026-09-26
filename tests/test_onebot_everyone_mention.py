from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from nonebot.exception import IgnoredException

from ironsbot.integrations.onebot.ingress_policy import OneBotIngressPolicy
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.rules import (
    bot_mention,
    explicit_command,
    member_target_command,
    natural_language,
)
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.router import BotRouter


@dataclass
class _RejectingRouter:
    calls: int = 0

    def allows_incoming(self, _bot_id: int, _conversation: object) -> bool:
        self.calls += 1
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["help", "1", "hello"])
@pytest.mark.parametrize("with_bot", [False, True])
async def test_everyone_mention_is_silent_even_when_addressing_bot(
    text: str, *, with_bot: bool
) -> None:
    message = Message(MessageSegment.at("all"))
    if with_bot:
        message += MessageSegment.at(1)
    message += MessageSegment.text(text)
    event = group_message_event(message=message)
    context = message_input_context(event)
    assert context.mentions_everyone
    assert context.has_any_mention
    assert context.member_mentions == ()
    with pytest.raises(IgnoredException):
        await OneBotIngressPolicy(messages_enabled=True).process(event)
    for rule in (
        explicit_command(),
        member_target_command(),
        bot_mention(),
        natural_language(),
    ):
        assert not await rule(cast("Bot", None), event, {})


@pytest.mark.asyncio
async def test_quoted_everyone_mention_does_not_block_current_command() -> None:
    event = group_message_event("help", reply_sender_user_id=987)
    assert event.reply is not None
    event.reply.message = Message(MessageSegment.at("all"))
    assert not message_input_context(event).mentions_everyone
    await OneBotIngressPolicy(messages_enabled=True).process(event)
    assert await explicit_command()(cast("Bot", None), event, {})


@pytest.mark.asyncio
async def test_raw_everyone_mention_is_silent_when_adapter_removed_segment() -> None:
    event = group_message_event(
        "帮助",
        raw_message="[CQ:at,qq=all] 帮助",
        to_me=True,
    )

    assert message_input_context(event).mentions_everyone
    with pytest.raises(IgnoredException):
        await OneBotIngressPolicy(messages_enabled=True).process(event)


@pytest.mark.asyncio
async def test_unconfigured_group_is_ignored_even_when_bot_is_mentioned() -> None:
    router = _RejectingRouter()
    event = group_message_event(
        message=Message(MessageSegment.at(1)) + MessageSegment.text("帮助")
    )

    with pytest.raises(IgnoredException):
        await OneBotIngressPolicy(
            messages_enabled=True,
            router=cast("BotRouter", router),
        ).process(event)

    assert router.calls == 1
