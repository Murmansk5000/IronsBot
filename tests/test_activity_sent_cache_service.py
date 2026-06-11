from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ironsbot.services.activity.models import ActivityReminder
from ironsbot.services.activity.sent_cache import filter_unsent, mark_sent

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def dt(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ)


def _reminder(activity_id: int = 1) -> ActivityReminder:
    return ActivityReminder(
        activity_id=activity_id,
        name=f"活动 {activity_id}",
        end_time=dt(2026, 6, 12, 10),
        lead_hours=1,
        send_time=dt(2026, 6, 12, 9),
    )


def test_filter_unsent_returns_missing_reminders(tmp_path: Path) -> None:
    cache_path = tmp_path / "sent.sqlite"
    reminders = [_reminder(1), _reminder(2)]

    assert filter_unsent(reminders, cache_path=cache_path) == reminders

    mark_sent(
        [reminders[0]],
        cache_path=cache_path,
        sent_at=dt(2026, 6, 12, 9),
    )

    assert filter_unsent(reminders, cache_path=cache_path) == [reminders[1]]


def test_mark_sent_is_idempotent(tmp_path: Path) -> None:
    cache_path = tmp_path / "sent.sqlite"
    reminder = _reminder()

    mark_sent([reminder], cache_path=cache_path, sent_at=dt(2026, 6, 12, 9))
    mark_sent([reminder], cache_path=cache_path, sent_at=dt(2026, 6, 12, 9))

    assert filter_unsent([reminder], cache_path=cache_path) == []
