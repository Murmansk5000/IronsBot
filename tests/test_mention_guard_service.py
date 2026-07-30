from ironsbot.services.messaging.mention_guard import (
    REPEATED_MENTION_MESSAGE,
    MentionGuardService,
)


def test_mention_guard_replies_once_then_warns_once_then_stays_silent() -> None:
    service = MentionGuardService()

    assert service.admit(123, now=0).should_send_help
    assert service.admit(123, now=1).reply == REPEATED_MENTION_MESSAGE
    assert service.admit(123, now=2).reply is None
    assert service.admit(456, now=2).should_send_help


def test_mention_guard_counts_only_initial_replies_in_ten_minute_window() -> None:
    service = MentionGuardService()

    assert service.admit(123, now=0).should_send_help
    assert service.admit(123, now=1).reply == REPEATED_MENTION_MESSAGE
    assert service.admit(123, now=60).should_send_help
    assert service.admit(123, now=120).should_send_help

    assert service.admit(123, now=180).reply is None
    assert service.admit(123, now=600).should_send_help
