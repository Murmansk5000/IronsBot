from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ironsbot.core.bilibili import BiliBoostWindow, BiliPollingConfig
from ironsbot.core.time import clock_window_contains, second_of_day

POLLING_WINDOW_TIME_ERROR = "bilibili.polling.windows time must use HH:MM:SS"
_SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(slots=True)
class AutoCheckState:
    last_checked_at: datetime | None = None
    completed_boost_slots: dict[str, datetime] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BoostSlot:
    window_index: int
    starts_at: datetime

    @property
    def key(self) -> str:
        return f"{self.window_index}:{self.starts_at.isoformat()}"


@dataclass(frozen=True, slots=True)
class BoostScheduleEntry:
    hour: int
    minute: int
    second: int

    @property
    def job_suffix(self) -> str:
        return f"boost_{self.hour:02d}{self.minute:02d}{self.second:02d}"


def window_contains(now: datetime, *, start: str, end: str) -> bool:
    return clock_window_contains(
        now,
        start=start,
        end=end,
        error_message=POLLING_WINDOW_TIME_ERROR,
    )


def current_interval_minutes(
    polling: BiliPollingConfig,
    now: datetime,
) -> int:
    for window in polling.windows:
        if window_contains(now, start=window.start, end=window.end):
            return window.minutes
    return polling.default_minutes


def current_polling_slot_start(
    polling: BiliPollingConfig,
    now: datetime,
) -> datetime:
    current_second = (now.hour * 60 + now.minute) * 60 + now.second
    interval = polling.default_minutes
    anchor_second = 0
    for window in polling.windows:
        if not window_contains(now, start=window.start, end=window.end):
            continue
        interval = window.minutes
        anchor_second = second_of_day(
            window.start,
            error_message=POLLING_WINDOW_TIME_ERROR,
        )
        if current_second < anchor_second:
            anchor_second -= 24 * 60 * 60
        break

    elapsed_seconds = current_second - anchor_second
    slot_second = anchor_second + (elapsed_seconds // (interval * 60)) * interval * 60
    day_offset, second_of_day_value = divmod(slot_second, 24 * 60 * 60)
    return now.replace(
        hour=second_of_day_value // 3600,
        minute=(second_of_day_value % 3600) // 60,
        second=second_of_day_value % 60,
        microsecond=0,
    ) + timedelta(days=day_offset)


def auto_check_due(
    state: AutoCheckState,
    polling: BiliPollingConfig,
    now: datetime,
) -> bool:
    if state.last_checked_at is None:
        return True

    current_slot = current_polling_slot_start(polling, now)
    return state.last_checked_at < current_slot


def mark_auto_check(state: AutoCheckState, now: datetime) -> None:
    state.last_checked_at = now


def boost_schedule_entries(
    polling: BiliPollingConfig,
) -> tuple[BoostScheduleEntry, ...]:
    """Return the finite daily cron entries configured for release bursts."""

    entries: set[BoostScheduleEntry] = set()
    for window in polling.boost_windows:
        for slot_second in _boost_slot_seconds(window):
            hour, remaining = divmod(slot_second, 60 * 60)
            minute = remaining // 60
            entries.update(
                BoostScheduleEntry(hour, minute, offset)
                for offset in window.offset_seconds
            )
    return tuple(
        sorted(entries, key=lambda item: (item.hour, item.minute, item.second))
    )


def boost_slots_at(
    polling: BiliPollingConfig,
    now: datetime,
) -> tuple[BoostSlot, ...]:
    """Find burst slots matching this exact wall-clock second."""

    current_second = (now.hour * 60 + now.minute) * 60 + now.second
    slots: list[BoostSlot] = []
    for index, window in enumerate(polling.boost_windows):
        start_second = second_of_day(
            window.start,
            error_message=POLLING_WINDOW_TIME_ERROR,
        )
        end_second = second_of_day(
            window.end,
            error_message=POLLING_WINDOW_TIME_ERROR,
        )
        duration = (end_second - start_second) % _SECONDS_PER_DAY
        if duration == 0:
            continue
        anchor = now.replace(
            hour=start_second // 3600,
            minute=(start_second % 3600) // 60,
            second=0,
            microsecond=0,
        )
        if start_second > end_second and current_second < end_second:
            anchor -= timedelta(days=1)
        elapsed = int((now - anchor).total_seconds())
        if not 0 <= elapsed < duration:
            continue
        interval_seconds = window.interval_minutes * 60
        offset = elapsed % interval_seconds
        if offset not in window.offset_seconds:
            continue
        slots.append(
            BoostSlot(
                index,
                anchor + timedelta(seconds=elapsed - offset),
            )
        )
    return tuple(slots)


def boost_slots_due(
    state: AutoCheckState,
    slots: tuple[BoostSlot, ...],
) -> tuple[BoostSlot, ...]:
    return tuple(slot for slot in slots if slot.key not in state.completed_boost_slots)


def mark_boost_slots_completed(
    state: AutoCheckState,
    slots: tuple[BoostSlot, ...],
    now: datetime,
) -> None:
    cutoff = now - timedelta(days=2)
    state.completed_boost_slots = {
        key: completed_at
        for key, completed_at in state.completed_boost_slots.items()
        if completed_at >= cutoff
    }
    state.completed_boost_slots.update({slot.key: now for slot in slots})


def _boost_slot_seconds(window: BiliBoostWindow) -> tuple[int, ...]:
    start_second = second_of_day(window.start, error_message=POLLING_WINDOW_TIME_ERROR)
    end_second = second_of_day(window.end, error_message=POLLING_WINDOW_TIME_ERROR)
    duration = (end_second - start_second) % _SECONDS_PER_DAY
    if duration == 0:
        return ()
    interval_seconds = window.interval_minutes * 60
    return tuple(
        (start_second + elapsed) % _SECONDS_PER_DAY
        for elapsed in range(0, duration, interval_seconds)
    )
