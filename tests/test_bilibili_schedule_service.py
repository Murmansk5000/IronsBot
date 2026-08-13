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

BOOST_EXPECTED_WINDOW_COUNT = 2
BOOST_EXPECTED_TICK_COUNT = 4
BOOST_EXPECTED_REGULAR_SECOND = 5


def _boost_config(
    start: str,
    end: str,
    interval: int,
    offsets: list[int],
) -> BiliPollingConfig:
    return BiliPollingConfig(
        boost_windows=[
            BiliBoostWindow(
                start=start,
                end=end,
                interval_minutes=interval,
                offset_seconds=offsets,
            ),
        ],
    )


def test_boost_entries_use_configured_start_seconds() -> None:
    polling = _boost_config("12:00:30", "12:02:30", 1, [0, 5])
    assert boost_schedule_entries(polling) == (
        BoostScheduleEntry(12, 0, 30),
        BoostScheduleEntry(12, 0, 35),
        BoostScheduleEntry(12, 1, 30),
        BoostScheduleEntry(12, 1, 35),
    )


def test_boost_offset_carries_into_next_hour() -> None:
    polling = _boost_config("12:59:50", "13:01:50", 1, [0, 15])
    assert boost_schedule_entries(polling) == (
        BoostScheduleEntry(12, 59, 50),
        BoostScheduleEntry(13, 0, 5),
        BoostScheduleEntry(13, 0, 50),
        BoostScheduleEntry(13, 1, 5),
    )


def test_boost_offset_carries_into_next_day() -> None:
    polling = _boost_config("23:59:50", "00:01:50", 1, [0, 15])
    assert boost_schedule_entries(polling) == (
        BoostScheduleEntry(0, 0, 5),
        BoostScheduleEntry(0, 0, 50),
        BoostScheduleEntry(0, 1, 5),
        BoostScheduleEntry(23, 59, 50),
    )


def test_boost_last_interval_omits_offsets_at_or_after_end() -> None:
    polling = _boost_config("10:00:00", "10:02:05", 1, [0, 5, 10])
    assert boost_schedule_entries(polling) == tuple(
        BoostScheduleEntry(10, minute, second)
        for minute, second in (
            (0, 0), (0, 5), (0, 10), (1, 0), (1, 5), (1, 10), (2, 0)
        )
    )


def test_boost_nonzero_window_end_remains_exclusive() -> None:
    polling = _boost_config("12:00:30", "12:01:02", 1, [0, 31, 32, 59])
    assert boost_schedule_entries(polling) == (
        BoostScheduleEntry(12, 0, 30),
        BoostScheduleEntry(12, 1, 1),
    )
    assert not boost_slots_at(polling, _at(12, 1, 2))


def test_boost_overlapping_windows_deduplicate_physical_entries() -> None:
    polling = _boost_config("10:00:00", "10:02:00", 1, [0, 5])
    polling.boost_windows.append(polling.boost_windows[0].model_copy())
    assert len(boost_schedule_entries(polling)) == BOOST_EXPECTED_TICK_COUNT
    slots = boost_slots_at(polling, _at(10))
    assert tuple(slot.window_index for slot in slots) == (0, 1)
    assert len({slot.key for slot in slots}) == BOOST_EXPECTED_WINDOW_COUNT


def test_boost_original_offset_normalization_is_preserved() -> None:
    polling = _boost_config("10:00:00", "10:01:00", 1, [15, 0, 5])
    assert polling.boost_windows[0].offset_seconds == [0, 5, 15]
    assert boost_schedule_entries(polling) == (
        BoostScheduleEntry(10, 0, 0),
        BoostScheduleEntry(10, 0, 5),
        BoostScheduleEntry(10, 0, 15),
    )


def test_boost_interval_need_not_divide_window_duration() -> None:
    polling = _boost_config("10:00:00", "10:02:17", 2, [0, 15])
    assert boost_schedule_entries(polling) == (
        BoostScheduleEntry(10, 0, 0),
        BoostScheduleEntry(10, 0, 15),
        BoostScheduleEntry(10, 2, 0),
        BoostScheduleEntry(10, 2, 15),
    )


def test_boost_does_not_change_ordinary_polling() -> None:
    polling = _polling_config()
    polling.boost_windows = _boost_config(
        "07:59:50", "08:01:50", 1, [0, 15]
    ).boost_windows
    assert polling.check_second == BOOST_EXPECTED_REGULAR_SECOND
    assert current_interval_minutes(polling, _at(8)) == ACTIVE_INTERVAL_MINUTES
    state = AutoCheckState(last_checked_at=_at(8))
    assert not auto_check_due(state, polling, _at(8, 4, 59))
    assert auto_check_due(state, polling, _at(8, 5))


def test_boost_entries_match_nonzero_predicate_ticks() -> None:
    polling = _boost_config("12:00:30", "12:02:30", 1, [0, 5])
    expected = {
        BoostScheduleEntry(now.hour, now.minute, now.second)
        for elapsed in range(121)
        if boost_slots_at(
            polling, now := _at(12, 0, 30) + timedelta(seconds=elapsed)
        )
    }
    assert len(expected) == BOOST_EXPECTED_TICK_COUNT
    assert set(boost_schedule_entries(polling)) == expected


def test_boost_midnight_offset_keeps_previous_day_anchor() -> None:
    polling = _boost_config("23:59:50", "00:01:50", 1, [0, 15])
    slots = boost_slots_at(polling, _at(0, 0, 5) + timedelta(days=1))
    assert len(slots) == 1
    assert slots[0].starts_at == _at(23, 59, 50)
    assert boost_slots_at(polling, _at(0, 0, 50) + timedelta(days=1))[0].starts_at == (
        _at(0, 0, 50) + timedelta(days=1)
    )


def test_boost_completion_does_not_suppress_next_interval_or_day() -> None:
    polling = _boost_config("10:00:00", "10:02:00", 1, [0, 5])
    polling.boost_windows.append(polling.boost_windows[0].model_copy())
    state = AutoCheckState()
    first = boost_slots_at(polling, _at(10))
    mark_boost_slots_completed(state, first, _at(10))
    assert not boost_slots_due(state, boost_slots_at(polling, _at(10, 0, 5)))
    assert (
        len(boost_slots_due(state, boost_slots_at(polling, _at(10, 1))))
        == BOOST_EXPECTED_WINDOW_COUNT
    )
    tomorrow = boost_slots_at(polling, _at(10) + timedelta(days=1))
    assert len(boost_slots_due(state, tomorrow)) == BOOST_EXPECTED_WINDOW_COUNT

