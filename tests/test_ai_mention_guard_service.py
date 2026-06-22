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
