import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import IgnoredException
from pydantic import ValidationError

from ironsbot.config.models.settings import SelfCommandsConfig
from ironsbot.integrations.onebot.self_commands import (
    SelfCommandAdapter,
    SelfCommandGate,
)
from ironsbot.runtime.conversations import is_self_message_event
from ironsbot.runtime.message_input import is_self_command
from ironsbot.runtime.prompt_sessions import (
    GroupMenuAnchor,
    is_current_group_menu_reply,
)
from ironsbot.runtime.rules import (
    bot_mention,
    bot_mention_including_reply,
    natural_language,
)
from tests.helpers.onebot_events import group_message_event
from tests.test_runtime_rules import _matches


def test_self_command_requires_enable_and_prefix() -> None:
    event = group_message_event("演示 帮助", user_id=1)
    with pytest.raises(IgnoredException):
        SelfCommandGate(SelfCommandsConfig()).prepare(event)
    gate = SelfCommandGate(SelfCommandsConfig(enabled=True))
    with pytest.raises(IgnoredException):
        gate.prepare(group_message_event("帮助", user_id=1))
    gate.prepare(event)
    assert event.get_plaintext() == "帮助"
    assert event.user_id == event.self_id == 1
    assert is_self_command(event)
    assert not is_self_message_event(event)
    for rule in (natural_language(), bot_mention(), bot_mention_including_reply()):
        assert not _matches(rule, event)


def test_outbound_echo_and_duplicate_are_rejected() -> None:
    gate = SelfCommandGate(SelfCommandsConfig(enabled=True))
    gate.record_outbound(1, 456, Message("演示 帮助"))
    with pytest.raises(IgnoredException):
        gate.prepare(group_message_event("演示 帮助", user_id=1))
    gate.prepare(group_message_event("演示 精灵雷伊", user_id=1, message_id=4))
    with pytest.raises(IgnoredException):
        gate.prepare(group_message_event("演示 精灵雷伊", user_id=1, message_id=4))


@pytest.mark.parametrize("selection", ["1", "a1", "0"])
def test_prefixed_menu_reply(selection: str) -> None:
    gate = SelfCommandGate(SelfCommandsConfig(enabled=True))
    event = group_message_event(
        f"演示 {selection}",
        user_id=1,
        reply_sender_user_id=1,
        reply_message_id=10,
    )
    gate.prepare(event)
    assert event.get_plaintext() == selection
    assert is_current_group_menu_reply(event, GroupMenuAnchor(456, 1, 10))
    assert not is_current_group_menu_reply(event, GroupMenuAnchor(457, 1, 10))


def test_message_sent_adapter_and_ordinary_messages() -> None:
    original = group_message_event("演示 帮助", user_id=1)
    data = original.model_dump()
    data["post_type"] = "message_sent"
    parsed = SelfCommandAdapter.json_to_event(data)
    assert isinstance(parsed, GroupMessageEvent)
    assert parsed.user_id == 1
    gate = SelfCommandGate(SelfCommandsConfig(enabled=True))
    ordinary = group_message_event("精灵雷伊")
    gate.prepare(ordinary)
    assert ordinary.get_plaintext() == "精灵雷伊"
    assert not is_self_command(ordinary)


@pytest.mark.parametrize("prefix", ["", " ", [], ["演示 ", " "], [""]])
def test_blank_prefix_is_invalid(prefix: str | list[str]) -> None:
    with pytest.raises(ValidationError):
        SelfCommandsConfig(prefix=prefix)


@pytest.mark.parametrize("prefix", ["演示 ", "示范 "])
@pytest.mark.parametrize("command", ["帮助", "新增内容", "1", "a1", "0"])
def test_multiple_prefixes(prefix: str, command: str) -> None:
    gate = SelfCommandGate(
        SelfCommandsConfig(enabled=True, prefix=["演示 ", "示范 "])
    )
    event = group_message_event(f"{prefix}{command}", user_id=1)
    gate.prepare(event)
    assert event.get_plaintext() == command
    assert is_self_command(event)
    assert event.user_id == event.self_id
    assert not _matches(natural_language(), event)


@pytest.mark.parametrize("prefix", ["演示 ", "示范 "])
def test_multiple_prefix_outbound_echo_is_rejected(prefix: str) -> None:
    gate = SelfCommandGate(
        SelfCommandsConfig(enabled=True, prefix=["演示 ", "示范 "])
    )
    gate.record_outbound(1, 456, Message(f"{prefix}帮助"))
    with pytest.raises(IgnoredException):
        gate.prepare(group_message_event(f"{prefix}帮助", user_id=1))


def test_longest_prefix_wins_and_duplicate_message_cannot_switch_prefix() -> None:
    gate = SelfCommandGate(
        SelfCommandsConfig(enabled=True, prefix=["演", "演示 ", "演示 ", "示范 "])
    )
    event = group_message_event("演示 帮助", user_id=1, message_id=5)
    gate.prepare(event)
    assert event.get_plaintext() == "帮助"
    with pytest.raises(IgnoredException):
        gate.prepare(group_message_event("示范 帮助", user_id=1, message_id=5))
