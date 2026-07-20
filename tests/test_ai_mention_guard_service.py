from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from pytest import MonkeyPatch

from ironsbot.core.features import FeatureConfig, FeatureService
from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.plugins import ai
from ironsbot.plugins.ai import (
    _should_guard_non_ai_group_mention,
)
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from nonebot.adapters.onebot.v11 import GroupMessageEvent
    from nonebot.matcher import Matcher
    from nonebot.rule import Rule

    from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.messaging.help_hint import HelpHintService

    _GuardHandler = Callable[
        [Matcher, GroupMessageEvent], Coroutine[object, object, None]
    ]
    _Reply = tuple[Matcher, GroupMessageEvent, str]


def _features(*, ai_allowed: bool) -> FeatureService:
    return FeatureService(
        config=FeatureConfig(
            group_policy={"456": ["ai_chat"]} if ai_allowed else {},
            superuser_bypass=False,
        ),
        superuser_ids=frozenset(),
    )


@dataclass
class _InstalledMatcher:
    policy: CommandPolicy
    rule: Rule
    priority: int
    block: bool
    handlers: list[Callable[..., object]] = field(default_factory=list)

    def append_handler(self, handler: Callable[..., object]) -> None:
        self.handlers.append(handler)


class _InstalledRegistry:
    def __init__(self) -> None:
        self.matchers: list[_InstalledMatcher] = []

    def priority(self, _name: str) -> int:
        return 1

    def pre_command_priority(self, _name: str) -> int:
        return -1

    def on_message(
        self, *, policy: CommandPolicy, **kwargs: object
    ) -> _InstalledMatcher:
        matcher = _InstalledMatcher(
            policy=policy,
            rule=cast("Rule", kwargs["rule"]),
            priority=cast("int", kwargs["priority"]),
            block=cast("bool", kwargs["block"]),
        )
        self.matchers.append(matcher)
        return matcher


def _installed_guard(
    monkeypatch: MonkeyPatch, *, can_send: bool
) -> tuple[_GuardHandler, list[_Reply], list[int]]:
    registry = _InstalledRegistry()
    replies: list[_Reply] = []
    groups: list[int] = []

    async def finish(
        matcher: Matcher, event: GroupMessageEvent, message: str
    ) -> None:
        replies.append((matcher, event, message))

    def admit(group_id: int) -> bool:
        groups.append(group_id)
        return can_send

    monkeypatch.setattr(ai, "finish_event_reply", finish)
    ai.install(
        cast("MatcherRegistry", registry),
        cast("AiService", SimpleNamespace()),
        _features(ai_allowed=False),
        {},
        cast("HelpHintService", SimpleNamespace(can_send=admit)),
    )
    guard = registry.matchers[-1]
    assert guard.policy.command_id == "ai_mention_guard"
    assert guard.priority == -1
    assert guard.block is True
    assert len(guard.handlers) == 1
    return cast("_GuardHandler", guard.handlers[0]), replies, groups


@pytest.mark.parametrize(
    "text", ["@bot \u600e\u4e48\u7528", "@bot \u8c31\u5c3c\u914d\u7f6e"]
)
def test_installed_guard_uses_general_hint(monkeypatch: MonkeyPatch, text: str) -> None:
    handler, replies, groups = _installed_guard(monkeypatch, can_send=True)
    event = group_message_event(text)
    matcher = cast("Matcher", object())
    asyncio.run(handler(matcher, event))
    assert replies == [(matcher, event, DIRECT_COMMAND_HELP_HINT_TEXT)]
    assert groups == [event.group_id]


@pytest.mark.parametrize(
    "text", ["@bot \u600e\u4e48\u7528", "@bot \u8c31\u5c3c\u914d\u7f6e"]
)
def test_installed_guard_respects_hint_limit(
    monkeypatch: MonkeyPatch, text: str
) -> None:
    handler, replies, groups = _installed_guard(monkeypatch, can_send=False)
    event = group_message_event(text)
    asyncio.run(handler(cast("Matcher", object()), event))
    assert replies == []
    assert groups == [event.group_id]


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
