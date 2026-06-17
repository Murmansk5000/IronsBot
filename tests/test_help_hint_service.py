from dataclasses import dataclass

from ironsbot.services.help_hint import is_poke_at_bot
from ironsbot.shared.help_hints import (
    HELP_HINT_TEXT,
    append_help_hint,
    unsupported_feature_help_message,
)


@dataclass(frozen=True, slots=True)
class FakePokeEvent:
    self_id: int
    target_id: int


def test_append_help_hint_adds_shared_hint_once() -> None:
    assert append_help_hint("请直接发送指令") == f"请直接发送指令。{HELP_HINT_TEXT}"
    assert append_help_hint(f"请直接发送指令。{HELP_HINT_TEXT}") == (
        f"请直接发送指令。{HELP_HINT_TEXT}"
    )


def test_unsupported_feature_help_message_uses_shared_hint() -> None:
    assert unsupported_feature_help_message("查询精灵配置") == (
        f"此机器人暂不支持查询精灵配置。{HELP_HINT_TEXT}"
    )


def test_is_poke_at_bot_checks_poke_target() -> None:
    assert is_poke_at_bot(FakePokeEvent(self_id=100, target_id=100))
    assert not is_poke_at_bot(FakePokeEvent(self_id=100, target_id=200))
