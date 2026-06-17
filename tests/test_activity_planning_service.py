from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ironsbot.services.activity.models import ActivityInfo
from ironsbot.services.activity.planning import (
    activity_deadline,
    build_scheduled_reminders,
)

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def dt(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ)


def _first_week_offer_activity() -> ActivityInfo:
    return ActivityInfo(
        activity_id=1,
        name="首周皮肤活动",
        start_time=dt(2026, 6, 1, 10),
        end_time=dt(2026, 7, 1, 10),
        sort_order=1,
        offer_label="首周优惠",
        offer_window_days=7,
        offer_end_time=dt(2026, 6, 8, 0),
    )


def test_first_week_offer_deadline_uses_full_week_floor() -> None:
    activity = _first_week_offer_activity()

    deadline = activity_deadline(
        activity,
        dt(2026, 6, 7, 23),
        soon_ending_threshold=timedelta(days=7),
    )

    assert deadline is not None
    assert deadline.end_time == dt(2026, 6, 8, 10)
    assert deadline.label == "首周优惠"
    assert not deadline.display_end_time


def test_first_week_offer_stays_visible_until_full_week_end() -> None:
    activity = _first_week_offer_activity()

    assert activity_deadline(
        activity,
        dt(2026, 6, 8, 9),
        soon_ending_threshold=timedelta(days=7),
    ) is not None
    assert activity_deadline(
        activity,
        dt(2026, 6, 8, 10),
        soon_ending_threshold=timedelta(days=7),
    ) is not None
    assert activity_deadline(
        activity,
        dt(2026, 6, 8, 10, 1),
        soon_ending_threshold=timedelta(days=7),
    ) is None


def test_first_week_offer_schedules_late_night_and_morning_reminders() -> None:
    activity = _first_week_offer_activity()

    reminders = build_scheduled_reminders(
        [activity],
        dt(2026, 6, 7, 23),
        lead_hours=[11, 1],
        reminder_send_delay=timedelta(minutes=10),
        grace=timedelta(minutes=15),
        soon_ending_threshold=timedelta(days=7),
    )

    assert [(item.lead_hours, item.send_time) for item in reminders] == [
        (11, dt(2026, 6, 7, 23, 10)),
        (1, dt(2026, 6, 8, 9, 10)),
    ]
