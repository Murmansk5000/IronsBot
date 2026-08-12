from dataclasses import dataclass
from datetime import datetime, timedelta

from ironsbot.core.bilibili import BiliPollingConfig
from ironsbot.core.time import clock_window_contains, second_of_day

POLLING_WINDOW_TIME_ERROR = "bilibili.polling.windows time must use HH:MM:SS"


@dataclass(slots=True)
class AutoCheckState:
    last_checked_at: datetime | None = None


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
