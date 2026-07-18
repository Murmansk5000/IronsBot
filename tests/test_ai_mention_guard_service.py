import asyncio
from collections.abc import Callable
from importlib import import_module

from nonebot.adapters.onebot.v11 import MessageEvent
from pytest import MonkeyPatch

from ironsbot.config.models.ai import AiConfig
from ironsbot.config.models.feature import FeatureConfig
from ironsbot.services.ai import mention_guard
from ironsbot.services.ai.resources import AiResources
from ironsbot.shared.help_hints import (
    HELP_HINT_TEXT,
    PET_CONFIG_UNAVAILABLE_TEXT,
)
from tests.helpers.onebot_events import group_message_event
from tests.helpers.runtime import build_test_runtime


def _resources(*, ai_allowed: bool) -> AiResources:
    runtime = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy={"456": ["ai_chat"]} if ai_allowed else {},
            superuser_bypass=False,
        )
    )
    return AiResources(
        AiConfig(),
        runtime.features,
        runtime.admin_notices,
        "key",
        {},
        ("战队",),
        20,
    )


def _load_build_guard_message(
    monkeypatch: MonkeyPatch,
) -> Callable[[MessageEvent], str]:
    monkeypatch.setattr(
        "ironsbot.shared.matcher_priority.get_pre_command_matcher_priority",
        lambda _name: -1,
    )
    module = import_module("ironsbot.plugins.ai_mention_guard")
    return module._build_guard_message


def test_guard_message_uses_shared_hint(monkeypatch: MonkeyPatch) -> None:
    _build_guard_message = _load_build_guard_message(monkeypatch)

    assert _build_guard_message(group_message_event("@bot 怎么用")) == HELP_HINT_TEXT


def test_guard_message_appends_config_notice(monkeypatch: MonkeyPatch) -> None:
    _build_guard_message = _load_build_guard_message(monkeypatch)

    assert _build_guard_message(group_message_event("@bot 谱尼配置")) == (
        f"{HELP_HINT_TEXT}\n{PET_CONFIG_UNAVAILABLE_TEXT}"
    )


def test_config_mention_is_not_guarded_when_ai_is_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(mention_guard, "mentions_bot", lambda _event: True)

    assert not asyncio.run(
        mention_guard.should_guard_non_ai_group_mention(
            _resources(ai_allowed=True),
            group_message_event("@bot 谱尼配置")
        )
    )


def test_plain_mention_is_not_guarded_when_ai_is_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(mention_guard, "mentions_bot", lambda _event: True)

    assert not asyncio.run(
        mention_guard.should_guard_non_ai_group_mention(
            _resources(ai_allowed=True),
            group_message_event("@bot 谱尼强吗")
        )
    )


def test_foreign_mention_is_not_guarded(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(mention_guard, "mentions_bot", lambda _event: False)

    assert not asyncio.run(
        mention_guard.should_guard_non_ai_group_mention(
            _resources(ai_allowed=False),
            group_message_event("@someone 帮助")
        )
    )


def test_config_mention_is_guarded_when_ai_is_not_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(mention_guard, "mentions_bot", lambda _event: True)

    assert asyncio.run(
        mention_guard.should_guard_non_ai_group_mention(
            _resources(ai_allowed=False),
            group_message_event("@bot 谱尼配置")
        )
    )
