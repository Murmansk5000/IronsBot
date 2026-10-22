from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.integrations.onebot.received_messages import OneBotReceivedMessages
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from types import SimpleNamespace

    from ironsbot.services.onebot_routing import OneBotRoutingPolicy

pytest_plugins = ("tests.test_shared_onebot_ingress",)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["执行", "1", "hello"])
@pytest.mark.parametrize("with_bot", [False, True])
async def test_everyone_mention_is_silent_even_when_addressing_bot(
    runtime: SimpleNamespace, text: str, *, with_bot: bool
) -> None:
    message = Message(MessageSegment.at("all"))
    if with_bot:
        message += MessageSegment.at(1)
    message += MessageSegment.text(text)
    runtime.policies[runtime.group] = frozenset({"help", "ai_chat"})
    admission = Mock(decide=AsyncMock(side_effect=runtime.admission.decide))
    receiver = OneBotReceivedMessages(admission, runtime.router, runtime.messenger)
    await receiver.handle(
        runtime.bot, group_message_event(message=message, user_id=101).model_dump()
    )
    context = admission.decide.call_args.args[0].context
    assert context.mentions_everyone
    assert context.has_any_mention
    assert context.member_mentions == ()
    runtime.execute.assert_not_awaited()
    runtime.select.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []


@pytest.mark.asyncio
async def test_quoted_everyone_mention_does_not_block_current_command(
    runtime: SimpleNamespace,
) -> None:
    event = group_message_event("执行", user_id=101, reply_sender_user_id=987)
    assert event.reply is not None
    event.reply.message = Message(MessageSegment.at("all"))
    await runtime.received.handle(runtime.bot, event.model_dump())
    runtime.execute.assert_awaited_once()
    context = runtime.execute.call_args.args[1]
    assert not context.mentions_everyone
    assert context.member_mentions == ()
    assert len(runtime.sends) == 1
    runtime.ai.chat_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_everyone_mention_is_silent_when_adapter_removed_segment(
    runtime: SimpleNamespace,
) -> None:
    event = group_message_event(
        "执行", user_id=101, raw_message="[CQ:at,qq=all] 执行", to_me=True
    )
    await runtime.received.handle(runtime.bot, event.model_dump())
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []


@pytest.mark.asyncio
async def test_unconfigured_group_is_ignored_even_when_bot_is_mentioned(
    runtime: SimpleNamespace,
) -> None:
    router = Mock(allows_incoming=Mock(return_value=False))
    receiver = OneBotReceivedMessages(
        replace(runtime.admission, routing=cast("OneBotRoutingPolicy", router)),
        runtime.router,
        runtime.messenger,
    )
    event = group_message_event(
        user_id=101, message=Message(MessageSegment.at(1)) + MessageSegment.text("执行")
    )
    await receiver.handle(runtime.bot, event.model_dump())
    router.allows_incoming.assert_called_once_with(1, runtime.group)
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []
