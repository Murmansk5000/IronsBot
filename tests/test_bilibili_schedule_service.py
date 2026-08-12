from datetime import datetime, timedelta, timezone

from ironsbot.core.bilibili import BiliIntervalWindow, BiliPollingConfig
from ironsbot.services.bilibili.schedule import (
    AutoCheckState,
    auto_check_due,
    current_interval_minutes,
    current_polling_slot_start,
    mark_auto_check,
    window_contains,
)

ACTIVE_INTERVAL_MINUTES = 5
DEFAULT_INTERVAL_MINUTES = 30


def _at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, second, tzinfo=timezone.utc)


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


def test_window_contains_supports_second_boundaries() -> None:
    assert window_contains(_at(7, 0, 5), start="07:00:05", end="08:00:05")
    assert not window_contains(_at(8, 0, 5), start="07:00:05", end="08:00:05")


def test_current_interval_uses_matching_window_or_default() -> None:
    polling = _polling_config()

    assert current_interval_minutes(polling, _at(8)) == ACTIVE_INTERVAL_MINUTES
    assert current_interval_minutes(polling, _at(23)) == DEFAULT_INTERVAL_MINUTES


def test_auto_check_due_uses_polling_interval() -> None:
    polling = _polling_config()
    state = AutoCheckState()
    now = _at(8, 4)

    assert auto_check_due(state, polling, now)

    state.last_checked_at = _at(8, 1)
    assert not auto_check_due(state, polling, now)

    state.last_checked_at = _at(7, 59)
    assert auto_check_due(state, polling, now)


def test_polling_window_slots_are_anchored_to_configured_start() -> None:
    polling = BiliPollingConfig(
        default_minutes=30,
        windows=[BiliIntervalWindow(start="23:58", end="00:01", minutes=1)],
    )

    assert current_polling_slot_start(polling, _at(23, 58)) == _at(23, 58)
    assert current_polling_slot_start(polling, _at(23, 59)) == _at(23, 59)
    next_day = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
    assert current_polling_slot_start(polling, next_day) == next_day

    state = AutoCheckState(last_checked_at=_at(23, 59))
    assert auto_check_due(state, polling, next_day)
    mark_auto_check(state, next_day + timedelta(seconds=2))
    assert not auto_check_due(state, polling, next_day + timedelta(seconds=30))


def test_mark_auto_check_updates_state() -> None:
    state = AutoCheckState()
    now = _at(8)

    mark_auto_check(state, now)

    assert state.last_checked_at == now
