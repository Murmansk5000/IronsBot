from pytest import MonkeyPatch

from ironsbot.core.features import FeatureConfig, FeatureService
from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.plugins import ai
from ironsbot.plugins.ai import (
    _build_guard_message,
    _should_guard_non_ai_group_mention,
)
from tests.helpers.onebot_events import group_message_event
from tests.helpers.runtime import build_test_runtime


def _features(*, ai_allowed: bool) -> FeatureService:
    runtime = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy={"456": ["ai_chat"]} if ai_allowed else {},
            superuser_bypass=False,
        )
    )
    return runtime.features


def test_guard_message_uses_shared_hint() -> None:
    assert (
        _build_guard_message(group_message_event("@bot 怎么用"))
        == DIRECT_COMMAND_HELP_HINT_TEXT
    )


def test_guard_message_does_not_special_case_config() -> None:
    assert _build_guard_message(group_message_event("@bot 谱尼配置")) == (
        DIRECT_COMMAND_HELP_HINT_TEXT
    )


def test_config_mention_is_not_guarded_when_ai_is_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai, "mentions_bot", lambda _event: True)

    assert not _should_guard_non_ai_group_mention(
        _features(ai_allowed=True),
        group_message_event("@bot 谱尼配置"),
    )


def test_plain_mention_is_not_guarded_when_ai_is_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai, "mentions_bot", lambda _event: True)

    assert not _should_guard_non_ai_group_mention(
        _features(ai_allowed=True),
        group_message_event("@bot 谱尼强吗"),
    )


def test_foreign_mention_is_not_guarded(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai, "mentions_bot", lambda _event: False)

    assert not _should_guard_non_ai_group_mention(
        _features(ai_allowed=False),
        group_message_event("@someone 帮助"),
    )


def test_config_mention_is_guarded_when_ai_is_not_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai, "mentions_bot", lambda _event: True)

    assert _should_guard_non_ai_group_mention(
        _features(ai_allowed=False),
        group_message_event("@bot 谱尼配置"),
    )
