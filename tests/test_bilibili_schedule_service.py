from datetime import datetime, timedelta, timezone

from ironsbot.core.bilibili import (
    BiliBoostWindow,
    BiliIntervalWindow,
    BiliPollingConfig,
)
from ironsbot.services.bilibili.schedule import (
    AutoCheckState,
    BoostScheduleEntry,
    auto_check_due,
    boost_schedule_entries,
    boost_slots_at,
    boost_slots_due,
    current_interval_minutes,
    mark_auto_check,
    mark_boost_slots_completed,
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


def test_boost_slots_follow_offset_and_skip_completed_slot() -> None:
    polling = BiliPollingConfig(
        boost_windows=[
            BiliBoostWindow(
                start="10:00:00",
                end="11:00:00",
                interval_minutes=60,
                offset_seconds=[0, 5, 10, 15],
            )
        ]
    )
    state = AutoCheckState()
    first_slots = boost_slots_at(polling, _at(10))

    assert len(first_slots) == 1
    assert boost_slots_due(state, first_slots) == first_slots
    assert boost_schedule_entries(polling) == (
        BoostScheduleEntry(10, 0, 0),
        BoostScheduleEntry(10, 0, 5),
        BoostScheduleEntry(10, 0, 10),
        BoostScheduleEntry(10, 0, 15),
    )

    mark_boost_slots_completed(state, first_slots, _at(10))
    assert boost_slots_at(polling, _at(10, second=5)) == first_slots
    assert not boost_slots_due(state, first_slots)
    assert not boost_slots_at(polling, _at(11))


def test_boost_slots_support_midnight_windows() -> None:
    polling = BiliPollingConfig(
        boost_windows=[
            BiliBoostWindow(
                start="23:30:00",
                end="01:30:00",
                interval_minutes=60,
                offset_seconds=[5],
            )
        ]
    )

    slot = boost_slots_at(polling, _at(0, 30, 5) + timedelta(days=1))

    assert len(slot) == 1
    assert slot[0].starts_at == _at(0, 30) + timedelta(days=1)
