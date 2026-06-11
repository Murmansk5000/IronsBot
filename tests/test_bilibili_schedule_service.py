from datetime import datetime, timedelta, timezone

from ironsbot.config.models.bilibili import BiliIntervalWindow, BiliPollingConfig
from ironsbot.services.bilibili.schedule import (
    AutoCheckState,
    auto_check_due,
    current_interval_minutes,
    mark_auto_check,
    window_contains,
)

ACTIVE_INTERVAL_MINUTES = 5
DEFAULT_INTERVAL_MINUTES = 30


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, tzinfo=timezone.utc)


def _polling_config() -> BiliPollingConfig:
    return BiliPollingConfig(
        default_minutes=DEFAULT_INTERVAL_MINUTES,
        windows=[
            BiliIntervalWindow(
                start="07:00",
                end="23:00",
                minutes=ACTIVE_INTERVAL_MINUTES,
            )
        ],
    )


def test_window_contains_supports_normal_and_wrapped_windows() -> None:
    assert window_contains(_at(8), start="07:00", end="23:00")
    assert not window_contains(_at(23), start="07:00", end="23:00")

    assert window_contains(_at(23, 30), start="23:00", end="01:00")
    assert window_contains(_at(0, 30), start="23:00", end="01:00")
    assert not window_contains(_at(2), start="23:00", end="01:00")


def test_current_interval_uses_matching_window_or_default() -> None:
    polling = _polling_config()

    assert current_interval_minutes(polling, _at(8)) == ACTIVE_INTERVAL_MINUTES
    assert current_interval_minutes(polling, _at(23)) == DEFAULT_INTERVAL_MINUTES


def test_auto_check_due_uses_polling_interval() -> None:
    polling = _polling_config()
    state = AutoCheckState()
    now = _at(8)

    assert auto_check_due(state, polling, now)

    state.last_checked_at = now - timedelta(minutes=ACTIVE_INTERVAL_MINUTES - 1)
    assert not auto_check_due(state, polling, now)

    state.last_checked_at = now - timedelta(minutes=ACTIVE_INTERVAL_MINUTES)
    assert auto_check_due(state, polling, now)


def test_mark_auto_check_updates_state() -> None:
    state = AutoCheckState()
    now = _at(8)

    mark_auto_check(state, now)

    assert state.last_checked_at == now
