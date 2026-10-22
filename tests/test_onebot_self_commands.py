from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from pydantic import ValidationError

from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.core.outbound import SendResult
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.onebot.message_segments import onebot_own_account_input
from ironsbot.integrations.onebot.received_messages import OneBotReceivedMessages
from ironsbot.services.own_commands import OwnAccountCommandPolicy
from tests.helpers.onebot_events import (
    group_message_event,
    own_account_input,
    self_command_event,
)
from tests.helpers.onebot_inputs import message_input_context

if TYPE_CHECKING:
    from types import SimpleNamespace

    from tests.helpers.onebot_events import SentGroupFixture

pytest_plugins = ("tests.test_shared_onebot_ingress",)


def _accept(policy: OwnAccountCommandPolicy, event: SentGroupFixture) -> bool:
    return policy.accept(own_account_input(event)) is not None


@pytest.mark.parametrize("text", ["demo help", "demo 1", "demo 0"])
def test_self_commands_require_prefix_and_preserve_actor(text: str) -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    event = self_command_event(text)
    assert _accept(gate, event)
    command = gate.accept(own_account_input(event))
    assert command is not None and command.text == text.removeprefix("demo ")
    assert event.get_plaintext() == text
    assert event.user_id == event.self_id == 1
    assert _accept(gate, self_command_event(text))


@pytest.mark.parametrize("text", ["demo ", "help", "1", "0", "demography"])
def test_self_commands_reject_unprefixed_and_empty_input(text: str) -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    assert not _accept(gate, self_command_event(text))


def test_self_commands_default_disabled_and_longest_prefix_wins() -> None:
    assert not _accept(
        OwnAccountCommandPolicy(SelfCommandsConfig()), self_command_event("demo help")
    )
    gate = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo ", "demo long "])
    )
    event = self_command_event("demo long help")
    assert _accept(gate, event)
    command = gate.accept(own_account_input(event))
    assert command is not None and command.text == "help"
    assert event.get_plaintext() == "demo long help"


@pytest.mark.parametrize("prefixes", [[], [""], ["  "], ["demo ", ""]])
def test_self_command_prefix_configuration_rejects_empty_values(
    prefixes: list[str],
) -> None:
    with pytest.raises(ValidationError):
        SelfCommandsConfig(prefixes=prefixes)


@pytest.mark.asyncio
async def test_outbound_echo_cannot_trigger_self_command() -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    echo = onebot_own_account_input(
        "1",
        ConversationRef(Platform.ONEBOT, "group", "456"),
        [{"type": "text", "data": {"text": "demo help"}}],
        is_own_message=True,
    )
    assert echo is not None
    token = gate.begin_outbound(echo)
    gate.finish_outbound(token, SendResult(delivered=True, message_id="1"))
    assert not _accept(gate, self_command_event("demo help"))
    assert _accept(gate, self_command_event("demo about", message_id=4))


def test_self_command_rejects_mention_and_image_segments() -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    for segment in (MessageSegment.at(123), MessageSegment.image("test.png")):
        event = self_command_event("demo help")
        event.original_message = Message("demo help") + segment
        assert not _accept(gate, event)


def test_self_admin_binding_keeps_one_member_mention() -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig())
    event = self_command_event("绑定米米号123456")
    event.original_message = Message("绑定米米号123456") + MessageSegment.at(42)
    assert _accept(gate, event)
    assert event.get_plaintext() == "绑定米米号123456"
    assert [segment.type for segment in event.original_message] == ["text", "at"]
    targets = message_input_context(event).member_mentions
    assert tuple(actor.id for actor in targets) == ("42",)
    assert _accept(gate, event)


@pytest.mark.parametrize("text", ["绑定米米号", "绑定米米号123456 extra", "收集"])
def test_self_admin_binding_rejects_other_commands(text: str) -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig())
    event = self_command_event(text)
    event.original_message = Message(text) + MessageSegment.at(42)
    assert not _accept(gate, event)


def test_self_admin_binding_requires_exactly_one_other_member() -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig())
    for mentions in (
        Message(),
        MessageSegment.at(1),
        MessageSegment.at(42) + MessageSegment.at(43),
    ):
        event = self_command_event("绑定米米号123456")
        event.original_message = Message("绑定米米号123456") + mentions
        assert not _accept(gate, event)


@pytest.mark.asyncio
async def test_other_senders_are_observed_without_executing_self_commands(
    runtime: SimpleNamespace,
) -> None:
    data = group_message_event("demo help").model_dump()
    data["post_type"] = "message_sent"
    observer = Mock(observe_onebot=AsyncMock())
    receiver = OneBotReceivedMessages(
        replace(
            runtime.admission,
            identity_observer=observer,
            self_commands=OwnAccountCommandPolicy(
                SelfCommandsConfig(enabled=True, prefixes=["demo "])
            ),
        ),
        runtime.router,
        runtime.messenger,
    )
    await receiver.handle(runtime.bot, data)
    observer.observe_onebot.assert_awaited_once()
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []


@pytest.mark.asyncio
async def test_silent_mode_overrides_enabled_self_commands(
    runtime: SimpleNamespace,
) -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    event = self_command_event("demo 执行")
    payload = event.model_dump()
    payload["post_type"] = "message_sent"
    receiver = replace(
        runtime.received,
        admission=replace(
            runtime.admission, messages_enabled=False, self_commands=gate
        ),
    )
    await receiver.handle(runtime.bot, payload)
    assert event.get_plaintext() == "demo 执行"
    runtime.execute.assert_not_awaited()
    runtime.ai.chat_reply.assert_not_awaited()
    assert runtime.sends == []


@pytest.mark.asyncio
async def test_own_normalization_does_not_reparse_literal_cq(
    runtime: SimpleNamespace,
) -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    literal = "demo 米米号[CQ:at,qq=777]"
    event = self_command_event("demo help")
    event.message = Message(MessageSegment.text(literal))
    event.original_message = event.message.copy()
    event.raw_message = str(event.message)
    event.to_me = True
    payload = event.model_dump()
    payload["post_type"] = "message_sent"
    commands = Mock(handle=AsyncMock(return_value=False))
    receiver = OneBotReceivedMessages(
        replace(runtime.admission, self_commands=gate),
        Mock(ingress=commands),
        runtime.messenger,
    )
    await receiver.handle(runtime.bot, payload)
    commands.handle.assert_awaited_once()
    context = commands.handle.call_args.args[0]
    assert context.text == "米米号[CQ:at,qq=777]"
    assert context.member_mentions == ()
    assert not context.mentions_bot
    assert event.get_plaintext() == literal
    assert event.to_me
    assert [segment.type for segment in event.message] == ["text"]


@pytest.mark.asyncio
async def test_self_reply_quotes_request_without_mentioning_self(
    runtime: SimpleNamespace,
) -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    event = self_command_event("demo 执行")
    payload = event.model_dump()
    payload["post_type"] = "message_sent"
    receiver = replace(
        runtime.received, admission=replace(runtime.admission, self_commands=gate)
    )
    await receiver.handle(runtime.bot, payload)
    runtime.execute.assert_awaited_once()
    assert len(runtime.sends) == 1
    assert runtime.sends[0]["message"] == [
        {"type": "reply", "data": {"id": "-3"}},
        {"type": "text", "data": {"text": "result"}},
    ]


@pytest.mark.asyncio
async def test_admin_binding_passes_group_routing(runtime: SimpleNamespace) -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig())
    router = Mock()
    router.allows_incoming.return_value = False
    event = self_command_event("绑定米米号123456")
    event.message = Message("绑定米米号123456") + MessageSegment.at(42)
    payload = event.model_dump()
    payload["post_type"] = "message_sent"
    commands = Mock(handle=AsyncMock(return_value=False))
    receiver = OneBotReceivedMessages(
        replace(runtime.admission, self_commands=gate, routing=router),
        Mock(ingress=commands),
        runtime.messenger,
    )
    await receiver.handle(runtime.bot, payload)
    commands.handle.assert_awaited_once()
    context = commands.handle.call_args.args[0]
    assert context.text == "绑定米米号123456"
    assert tuple(actor.id for actor in context.member_mentions) == ("42",)
    router.allows_incoming.assert_not_called()
    rejected = self_command_event("收集").model_dump()
    rejected["post_type"] = "message_sent"
    await receiver.handle(runtime.bot, rejected)
    commands.handle.assert_awaited_once()
    assert runtime.sends == []
