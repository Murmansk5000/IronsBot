from dataclasses import dataclass
from datetime import datetime

from ironsbot.config.models.bilibili import BiliPollingConfig
from ironsbot.core.time import minute_of_day

POLLING_WINDOW_TIME_ERROR = "bilibili.polling.windows time must use HH:MM"


@dataclass(slots=True)
class AutoCheckState:
    last_checked_at: datetime | None = None


def window_contains(now: datetime, *, start: str, end: str) -> bool:
    current = now.hour * 60 + now.minute
    start_minute = minute_of_day(
        start,
        error_message=POLLING_WINDOW_TIME_ERROR,
    )
    end_minute = minute_of_day(
        end,
        error_message=POLLING_WINDOW_TIME_ERROR,
    )
    if start_minute <= end_minute:
        return start_minute <= current < end_minute
    return current >= start_minute or current < end_minute


def current_interval_minutes(
    polling: BiliPollingConfig,
    now: datetime,
) -> int:
    for window in polling.windows:
        if window_contains(now, start=window.start, end=window.end):
            return window.minutes
    return polling.default_minutes


def auto_check_due(
    state: AutoCheckState,
    polling: BiliPollingConfig,
    now: datetime,
) -> bool:
    if state.last_checked_at is None:
        return True

    interval = current_interval_minutes(polling, now)
    elapsed = now - state.last_checked_at
    return elapsed.total_seconds() >= interval * 60


def mark_auto_check(state: AutoCheckState, now: datetime) -> None:
    state.last_checked_at = now
