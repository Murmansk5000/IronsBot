from dataclasses import dataclass

from pytest import MonkeyPatch

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.runtime import HelpConfig
from ironsbot.services import help_hint
from ironsbot.services.help_hint import (
    get_group_poke_reply,
    get_poke_reply,
    get_user_poke_reply,
    is_poke_at_bot,
)
from ironsbot.shared.help_hints import (
    HELP_HINT_TEXT,
    PET_CONFIG_UNAVAILABLE_TEXT,
    append_help_hint,
)
from ironsbot.shared.messaging.rate_limits import sliding_window_rate_limiter
from tests.helpers.config import stub_app_config


@dataclass(slots=True)
class FakePokeEvent:
    self_id: int
    target_id: int


def test_append_help_hint_adds_shared_hint_once() -> None:
    assert append_help_hint("请直接发送指令") == f"请直接发送指令。{HELP_HINT_TEXT}"
    assert append_help_hint(f"请直接发送指令。{HELP_HINT_TEXT}") == (
        f"请直接发送指令。{HELP_HINT_TEXT}"
    )


def test_shared_help_hint_text_mentions_help_command() -> None:
    assert HELP_HINT_TEXT == "直接发送指令即可使用机器人功能；使用“帮助”指令获取帮助。"
    assert PET_CONFIG_UNAVAILABLE_TEXT == (
        "本机器人因无人搜集、整理、维护精灵配置图，无法开放配置查询功能。"
    )


def test_is_poke_at_bot_checks_poke_target() -> None:
    assert is_poke_at_bot(FakePokeEvent(self_id=100, target_id=100))
    assert not is_poke_at_bot(FakePokeEvent(self_id=100, target_id=200))


def test_group_poke_reply_prefers_configured_group_alias(
    monkeypatch: MonkeyPatch,
) -> None:
    config = stub_app_config(
        feature_config=FeatureConfig(group_aliases={"example": 987654321}),
        help_config=HelpConfig(poke_replies={"example": "自定义戳一戳回复"}),
    )
    monkeypatch.setattr(help_hint, "get_app_config", lambda: config)

    assert get_group_poke_reply(987654321) == "自定义戳一戳回复"
    assert get_group_poke_reply(876543210) is None


def test_group_poke_reply_accepts_numeric_group_id(
    monkeypatch: MonkeyPatch,
) -> None:
    config = stub_app_config(
        help_config=HelpConfig(poke_replies={"987654321": "数字群号回复"}),
    )
    monkeypatch.setattr(help_hint, "get_app_config", lambda: config)

    assert get_group_poke_reply(987654321) == "数字群号回复"


def test_user_poke_reply_accepts_chinese_user_alias(
    monkeypatch: MonkeyPatch,
) -> None:
    config = stub_app_config(
        feature_config=FeatureConfig(user_aliases={"示例昵称": 1234567890}),
        help_config=HelpConfig(
            poke_user_replies={"示例昵称": "用户专属回复"},
        ),
    )
    monkeypatch.setattr(help_hint, "get_app_config", lambda: config)

    assert get_user_poke_reply(1234567890) == "用户专属回复"
    assert get_user_poke_reply(9876543210) is None


def test_user_poke_reply_takes_priority_over_group_reply(
    monkeypatch: MonkeyPatch,
) -> None:
    config = stub_app_config(
        feature_config=FeatureConfig(
            group_aliases={"example": 987654321},
            user_aliases={"example_user": 1234567890},
        ),
        help_config=HelpConfig(
            poke_replies={"example": "群专属回复"},
            poke_user_replies={"example_user": "用户专属回复"},
        ),
    )
    monkeypatch.setattr(help_hint, "get_app_config", lambda: config)

    assert (
        get_poke_reply(group_id=987654321, user_id=1234567890)
        == "用户专属回复"
    )
    assert get_poke_reply(group_id=987654321, user_id=2345678901) == "群专属回复"


def test_help_hint_limiter_allows_three_group_hints_per_minute(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(help_hint, "get_app_config", stub_app_config)
    sliding_window_rate_limiter.clear(help_hint.HELP_HINT_RATE_LIMIT_NAMESPACE)
    now = 100.0

    assert help_hint.can_send_group_help_hint(987654321, now=now)
    assert help_hint.can_send_group_help_hint(987654321, now=now)
    assert help_hint.can_send_group_help_hint(987654321, now=now)
    assert not help_hint.can_send_group_help_hint(987654321, now=now)

    now = 160.0
    assert help_hint.can_send_group_help_hint(987654321, now=now)


def test_help_hint_limiter_counts_groups_independently(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(help_hint, "get_app_config", stub_app_config)
    sliding_window_rate_limiter.clear(help_hint.HELP_HINT_RATE_LIMIT_NAMESPACE)

    assert help_hint.can_send_group_help_hint(1, now=100.0)
    assert help_hint.can_send_group_help_hint(1, now=100.0)
    assert help_hint.can_send_group_help_hint(1, now=100.0)
    assert not help_hint.can_send_group_help_hint(1, now=100.0)
    assert help_hint.can_send_group_help_hint(2, now=100.0)
