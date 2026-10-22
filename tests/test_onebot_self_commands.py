from unittest.mock import Mock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.exception import IgnoredException
from pydantic import ValidationError

from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.outbound import SendResult
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.onebot.event_ingress import OneBotEventIngress
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_segments import onebot_own_account_input
from ironsbot.integrations.onebot.replies import build_event_reply_message
from ironsbot.integrations.onebot.self_commands import (
    SelfCommandAdapter,
    SentGroupMessageEvent,
)
from ironsbot.services.onebot_admission import OneBotAdmissionService
from ironsbot.services.own_commands import OwnAccountCommandPolicy
from tests.helpers.onebot_events import (
    group_message_event,
    own_account_input,
    self_command_event,
)

_FEATURES = FeatureService({}, {}, frozenset())


def _accept(policy: OwnAccountCommandPolicy, event: SentGroupMessageEvent) -> bool:
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


def test_other_senders_are_not_converted_to_self_commands() -> None:
    data = group_message_event("demo help").model_dump()
    data["post_type"] = "message_sent"
    assert not isinstance(SelfCommandAdapter.json_to_event(data), SentGroupMessageEvent)


@pytest.mark.asyncio
async def test_silent_mode_overrides_enabled_self_commands() -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    event = self_command_event("demo help")
    with pytest.raises(IgnoredException):
        await OneBotEventIngress(
            OneBotAdmissionService(
                messages_enabled=False, features=_FEATURES, self_commands=gate
            )
        ).process(event)
    assert event.get_plaintext() == "demo help"


@pytest.mark.asyncio
async def test_own_normalization_does_not_reparse_literal_cq() -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    literal = "demo 米米号[CQ:at,qq=777]"
    event = self_command_event("demo help")
    event.message = Message(MessageSegment.text(literal))
    event.original_message = event.message.copy()
    event.raw_message = str(event.message)
    event.to_me = True
    context = await OneBotEventIngress(
        OneBotAdmissionService(
            messages_enabled=True, features=_FEATURES, self_commands=gate
        )
    ).process(event)
    assert context is not None
    assert context.text == "米米号[CQ:at,qq=777]"
    assert context.member_mentions == ()
    assert not context.mentions_bot
    assert event.get_plaintext() == literal
    assert event.to_me
    assert [segment.type for segment in event.message] == ["text"]


@pytest.mark.asyncio
async def test_self_reply_quotes_request_without_mentioning_self() -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    event = self_command_event("demo help")
    await OneBotEventIngress(
        OneBotAdmissionService(
            messages_enabled=True, features=_FEATURES, self_commands=gate
        )
    ).process(event)
    message = build_event_reply_message(event, "result")
    assert [segment.type for segment in message] == ["reply", "text"]
    assert message[0].data["id"] == "-3"


@pytest.mark.asyncio
async def test_admin_binding_passes_group_routing() -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig())
    router = Mock()
    router.allows_incoming.return_value = False
    event = self_command_event("绑定米米号123456")
    event.original_message = Message("绑定米米号123456") + MessageSegment.at(42)
    context = await OneBotEventIngress(
        OneBotAdmissionService(
            messages_enabled=True,
            features=_FEATURES,
            self_commands=gate,
            routing=router,
        )
    ).process(event)
    assert context is not None and context.text == "绑定米米号123456"
    assert tuple(actor.id for actor in context.member_mentions) == ("42",)
    router.allows_incoming.assert_not_called()
    with pytest.raises(IgnoredException):
        await OneBotEventIngress(
            OneBotAdmissionService(
                messages_enabled=True,
                features=_FEATURES,
                self_commands=gate,
                routing=router,
            )
        ).process(self_command_event("收集"))
