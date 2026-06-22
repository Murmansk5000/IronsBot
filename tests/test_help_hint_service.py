from dataclasses import dataclass

from ironsbot.services.help_hint import HelpHintLimiter, is_poke_at_bot
from ironsbot.shared.help_hints import (
    HELP_HINT_TEXT,
    PET_CONFIG_UNAVAILABLE_TEXT,
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


def test_shared_help_hint_text_mentions_help_command() -> None:
    assert HELP_HINT_TEXT == "直接发送指令即可使用机器人功能；使用“帮助”指令获取帮助。"
    assert PET_CONFIG_UNAVAILABLE_TEXT == (
        "本机器人因无人搜集、整理、维护精灵配置图，无法开放配置查询功能。"
    )


def test_is_poke_at_bot_checks_poke_target() -> None:
    assert is_poke_at_bot(FakePokeEvent(self_id=100, target_id=100))
    assert not is_poke_at_bot(FakePokeEvent(self_id=100, target_id=200))


def test_help_hint_limiter_allows_three_group_hints_per_minute() -> None:
    now = 100.0
    limiter = HelpHintLimiter(clock=lambda: now)

    assert limiter.can_send(686376929)
    assert limiter.can_send(686376929)
    assert limiter.can_send(686376929)
    assert not limiter.can_send(686376929)

    now = 160.0
    assert limiter.can_send(686376929)


def test_help_hint_limiter_counts_groups_independently() -> None:
    limiter = HelpHintLimiter(clock=lambda: 100.0)

    assert limiter.can_send(1)
    assert limiter.can_send(1)
    assert limiter.can_send(1)
    assert not limiter.can_send(1)
    assert limiter.can_send(2)
