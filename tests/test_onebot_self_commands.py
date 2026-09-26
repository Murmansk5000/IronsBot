from typing import cast
from unittest.mock import Mock

import pytest
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from nonebot.exception import IgnoredException
from pydantic import ValidationError

from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.integrations.onebot import self_commands
from ironsbot.integrations.onebot.ingress_policy import OneBotIngressPolicy
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.replies import build_event_reply_message
from ironsbot.integrations.onebot.self_commands import (
    SelfCommandAdapter,
    SelfCommandEvent,
    SelfCommandGate,
)
from tests.helpers.onebot_events import group_message_event


def _event(text: str, message_id: int = -3) -> SelfCommandEvent:
    data = group_message_event(text, user_id=1, message_id=message_id).model_dump()
    data["post_type"] = "message_sent"
    event = SelfCommandAdapter.json_to_event(data)
    assert isinstance(event, SelfCommandEvent)
    return event


@pytest.mark.parametrize("text", ["demo help", "demo 1", "demo 0"])
def test_self_commands_require_prefix_and_preserve_actor(text: str) -> None:
    gate = SelfCommandGate(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    event = _event(text)
    assert gate.accept(event)
    assert event.get_plaintext() == text.removeprefix("demo ")
    assert event.user_id == event.self_id == 1
    assert event.accepted
    assert not gate.accept(_event(text))


@pytest.mark.parametrize("text", ["demo ", "help", "1", "0", "demography"])
def test_self_commands_reject_unprefixed_and_empty_input(text: str) -> None:
    gate = SelfCommandGate(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    assert not gate.accept(_event(text))


def test_self_commands_default_disabled_and_longest_prefix_wins() -> None:
    assert not SelfCommandGate(SelfCommandsConfig()).accept(_event("demo help"))
    gate = SelfCommandGate(
        SelfCommandsConfig(enabled=True, prefixes=["demo ", "demo long "])
    )
    event = _event("demo long help")
    assert gate.accept(event)
    assert event.get_plaintext() == "help"


@pytest.mark.parametrize("prefixes", [[], [""], ["  "], ["demo ", ""]])
def test_self_command_prefix_configuration_rejects_empty_values(
    prefixes: list[str],
) -> None:
    with pytest.raises(ValidationError):
        SelfCommandsConfig(prefixes=prefixes)


@pytest.mark.asyncio
async def test_outbound_echo_cannot_trigger_self_command() -> None:
    gate = SelfCommandGate(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    bot = cast("Bot", Mock(self_id="1"))
    await gate.record_outbound(
        bot, "send_group_msg", {"group_id": 456, "message": "demo help"}
    )
    assert not gate.accept(_event("demo help"))
    assert gate.accept(_event("demo about", message_id=4))


def test_self_command_rejects_mention_and_image_segments() -> None:
    gate = SelfCommandGate(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    for segment in (MessageSegment.at(123), MessageSegment.image("test.png")):
        event = _event("demo help")
        event.original_message = Message("demo help") + segment
        assert not gate.accept(event)


def test_self_admin_binding_keeps_one_member_mention() -> None:
    gate = SelfCommandGate(SelfCommandsConfig())
    event = _event("绑定米米号123456")
    event.original_message = Message("绑定米米号123456") + MessageSegment.at(42)
    assert gate.accept(event)
    assert event.get_plaintext() == "绑定米米号123456"
    assert [segment.type for segment in event.message] == ["at", "text"]
    targets = message_input_context(event).member_mentions
    assert tuple(actor.id for actor in targets) == (
        "42",
    )
    assert not gate.accept(event)


@pytest.mark.parametrize("text", ["绑定米米号", "绑定米米号123456 extra", "收集"])
def test_self_admin_binding_rejects_other_commands(text: str) -> None:
    gate = SelfCommandGate(SelfCommandsConfig())
    event = _event(text)
    event.original_message = Message(text) + MessageSegment.at(42)
    assert not gate.accept(event)


def test_self_admin_binding_requires_exactly_one_other_member() -> None:
    gate = SelfCommandGate(SelfCommandsConfig())
    for mentions in (
        Message(),
        MessageSegment.at(1),
        MessageSegment.at(42) + MessageSegment.at(43),
    ):
        event = _event("绑定米米号123456")
        event.original_message = Message("绑定米米号123456") + mentions
        assert not gate.accept(event)


def test_other_senders_are_not_converted_to_self_commands() -> None:
    data = group_message_event("demo help").model_dump()
    data["post_type"] = "message_sent"
    assert not isinstance(SelfCommandAdapter.json_to_event(data), SelfCommandEvent)


@pytest.mark.asyncio
async def test_silent_mode_overrides_enabled_self_commands() -> None:
    gate = SelfCommandGate(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    event = _event("demo help")
    with pytest.raises(IgnoredException):
        await OneBotIngressPolicy(messages_enabled=False, self_commands=gate).process(
            event
        )
    assert not event.accepted


@pytest.mark.asyncio
async def test_self_reply_quotes_request_without_mentioning_self() -> None:
    gate = SelfCommandGate(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    event = _event("demo help")
    await OneBotIngressPolicy(messages_enabled=True, self_commands=gate).process(event)
    message = build_event_reply_message(event, "result")
    assert [segment.type for segment in message] == ["reply", "text"]
    assert message[0].data["id"] == "-3"


@pytest.mark.asyncio
async def test_admin_binding_passes_group_routing() -> None:
    gate = SelfCommandGate(SelfCommandsConfig())
    router = Mock()
    router.allows_incoming.return_value = False
    event = _event("绑定米米号123456")
    event.original_message = Message("绑定米米号123456") + MessageSegment.at(42)
    await OneBotIngressPolicy(
        messages_enabled=True,
        self_commands=gate,
        router=router,
    ).process(event)
    assert event.admin_binding
    router.allows_incoming.assert_not_called()
    with pytest.raises(IgnoredException):
        await OneBotIngressPolicy(
            messages_enabled=True,
            self_commands=gate,
            router=router,
        ).process(_event("收集"))


def test_self_command_replay_retention_is_bounded_and_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(self_commands, "monotonic", lambda: 1000.0)
    gate = SelfCommandGate(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    for index in range(4100):
        assert gate.accept(_event("demo help", message_id=index))
    assert not gate.accept(_event("demo help", message_id=4099))
    assert gate.accept(_event("demo help", message_id=0))
    monkeypatch.setattr(self_commands, "monotonic", lambda: 1601.0)
    assert gate.accept(_event("demo help", message_id=4099))
