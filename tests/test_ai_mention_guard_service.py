import asyncio

from pytest import MonkeyPatch

from ironsbot.services.ai import mention_guard
from ironsbot.services.ai.mention_guard import GuardReplyLimiter
from ironsbot.shared.help_hints import (
    HELP_HINT_TEXT,
    PET_CONFIG_UNAVAILABLE_TEXT,
)


class FakeMessageEvent:
    def __init__(self, text: str) -> None:
        self.text = text

    def get_plaintext(self) -> str:
        return self.text


class FakeGroupMessageEvent(FakeMessageEvent):
    pass


def test_guard_reply_limiter_caps_messages_per_window() -> None:
    now = 100.0
    limiter = GuardReplyLimiter(
        window_seconds=60.0,
        max_per_window=2,
        clock=lambda: now,
    )

    assert limiter.can_send(123)
    assert limiter.can_send(123)
    assert not limiter.can_send(123)


def test_guard_reply_limiter_expires_old_messages() -> None:
    current_time = 100.0

    def clock() -> float:
        return current_time

    limiter = GuardReplyLimiter(
        window_seconds=60.0,
        max_per_window=1,
        clock=clock,
    )

    assert limiter.can_send(123)
    assert not limiter.can_send(123)

    current_time = 160.0
    assert limiter.can_send(123)


def test_guard_message_uses_shared_hint() -> None:
    from ironsbot.plugins.ai_mention_guard import _build_guard_message

    assert _build_guard_message(FakeMessageEvent("@bot 怎么用")) == HELP_HINT_TEXT


def test_guard_message_appends_config_notice() -> None:
    from ironsbot.plugins.ai_mention_guard import _build_guard_message

    assert _build_guard_message(FakeMessageEvent("@bot 谱尼配置")) == (
        f"{HELP_HINT_TEXT}\n{PET_CONFIG_UNAVAILABLE_TEXT}"
    )


def test_config_mention_is_not_guarded_when_ai_is_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(mention_guard, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(mention_guard, "mentions_bot", lambda _event: True)
    monkeypatch.setattr(mention_guard, "is_ai_allowed", lambda _event: True)

    assert not asyncio.run(
        mention_guard.should_guard_non_ai_group_mention(
            FakeGroupMessageEvent("@bot 谱尼配置")
        )
    )


def test_plain_mention_is_not_guarded_when_ai_is_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(mention_guard, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(mention_guard, "mentions_bot", lambda _event: True)
    monkeypatch.setattr(mention_guard, "is_ai_allowed", lambda _event: True)

    assert not asyncio.run(
        mention_guard.should_guard_non_ai_group_mention(
            FakeGroupMessageEvent("@bot 谱尼强吗")
        )
    )


def test_config_mention_is_guarded_when_ai_is_not_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(mention_guard, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(mention_guard, "mentions_bot", lambda _event: True)
    monkeypatch.setattr(mention_guard, "is_ai_allowed", lambda _event: False)

    assert asyncio.run(
        mention_guard.should_guard_non_ai_group_mention(
            FakeGroupMessageEvent("@bot 谱尼配置")
        )
    )
