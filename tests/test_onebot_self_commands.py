from typing import cast
from unittest.mock import Mock

import pytest
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from nonebot.exception import IgnoredException
from pydantic import ValidationError

from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.integrations.onebot.event_ingress import OneBotEventIngress
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.replies import build_event_reply_message
from ironsbot.integrations.onebot.self_commands import (
    SelfCommandAdapter,
    SelfCommandEvent,
    own_account_echo,
    own_account_input,
)
from ironsbot.services.onebot_admission import OneBotAdmissionService
from ironsbot.services.own_commands import OwnAccountCommandPolicy
from tests.helpers.onebot_events import group_message_event, self_command_event


def _accept(policy: OwnAccountCommandPolicy, event: SelfCommandEvent) -> bool:
    command = policy.accept(own_account_input(event))
    if command is not None:
        event.apply_command(command)
    return command is not None


@pytest.mark.parametrize("text", ["demo help", "demo 1", "demo 0"])
def test_self_commands_require_prefix_and_preserve_actor(text: str) -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    event = self_command_event(text)
    assert _accept(gate, event)
    assert event.get_plaintext() == text.removeprefix("demo ")
    assert event.user_id == event.self_id == 1
    assert event.accepted
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
    assert event.get_plaintext() == "help"


@pytest.mark.parametrize("prefixes", [[], [""], ["  "], ["demo ", ""]])
def test_self_command_prefix_configuration_rejects_empty_values(
    prefixes: list[str],
) -> None:
    with pytest.raises(ValidationError):
        SelfCommandsConfig(prefixes=prefixes)


@pytest.mark.asyncio
async def test_outbound_echo_cannot_trigger_self_command() -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    bot = cast("Bot", Mock(self_id="1"))
    echo = own_account_echo(
        bot, "send_group_msg", {"group_id": 456, "message": "demo help"}
    )
    assert echo is not None
    gate.record_outbound(echo)
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
    assert [segment.type for segment in event.message] == ["at", "text"]
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
    assert not isinstance(SelfCommandAdapter.json_to_event(data), SelfCommandEvent)


@pytest.mark.asyncio
async def test_silent_mode_overrides_enabled_self_commands() -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    event = self_command_event("demo help")
    with pytest.raises(IgnoredException):
        await OneBotEventIngress(
            OneBotAdmissionService(messages_enabled=False, self_commands=gate)
        ).process(event)
    assert not event.accepted


@pytest.mark.asyncio
async def test_self_reply_quotes_request_without_mentioning_self() -> None:
    gate = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=["demo "]))
    event = self_command_event("demo help")
    await OneBotEventIngress(
        OneBotAdmissionService(messages_enabled=True, self_commands=gate)
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
    await OneBotEventIngress(
        OneBotAdmissionService(
            messages_enabled=True,
            self_commands=gate,
            routing=router,
        )
    ).process(event)
    assert event.admin_binding
    router.allows_incoming.assert_not_called()
    with pytest.raises(IgnoredException):
        await OneBotEventIngress(
            OneBotAdmissionService(
                messages_enabled=True,
                self_commands=gate,
                routing=router,
            )
        ).process(self_command_event("收集"))


@pytest.mark.asyncio
async def test_native_echo_hook_blocks_admin_binding_even_with_prefix_commands_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot.adapters import Bot as AdapterBot

    from ironsbot.integrations.onebot import event_ingress

    register = Mock()
    monkeypatch.setattr(Bot, "on_calling_api", register)
    monkeypatch.setattr(event_ingress, "event_preprocessor", lambda handler: handler)
    policy = OwnAccountCommandPolicy(SelfCommandsConfig())
    admission = OneBotEventIngress(
        OneBotAdmissionService(messages_enabled=True, self_commands=policy)
    )
    admission.install()
    register.assert_called_once()
    hook = register.call_args.args[0]
    message = Message("绑定米米号123456") + MessageSegment.at(42)
    await hook(
        Mock(spec=AdapterBot, self_id="1"),
        "send_group_msg",
        {
            "group_id": 456,
            "message": message,
        },
    )
    candidate = self_command_event("绑定米米号123456")
    candidate.original_message = message
    assert policy.accept(own_account_input(candidate)) is not None
    await hook(
        cast("Bot", Mock(spec=Bot, self_id="1")),
        "send_group_msg",
        {
            "group_id": 456,
            "message": message,
        },
    )
    event = self_command_event("绑定米米号123456")
    event.original_message = message
    with pytest.raises(IgnoredException):
        await admission.process(event)
    assert not event.accepted
