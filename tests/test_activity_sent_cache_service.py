from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ironsbot.integrations.storage.activity import (
    ActivitySentStore,
    ActivitySnapshotStore,
)
from ironsbot.services.activity.models import ActivityReminder

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
    store = ActivitySentStore(cache_path)
    reminders = [_reminder(1), _reminder(2)]

    assert store.filter_unsent(reminders) == reminders

    store.mark_sent(
        [reminders[0]],
        sent_at=dt(2026, 6, 12, 9),
    )

    assert store.filter_unsent(reminders) == [reminders[1]]


def test_mark_sent_is_idempotent(tmp_path: Path) -> None:
    cache_path = tmp_path / "sent.sqlite"
    store = ActivitySentStore(cache_path)
    reminder = _reminder()

    store.mark_sent([reminder], sent_at=dt(2026, 6, 12, 9))
    store.mark_sent([reminder], sent_at=dt(2026, 6, 12, 9))

    assert store.filter_unsent([reminder]) == []


def test_activity_snapshot_store_compares_the_previous_week(tmp_path: Path) -> None:
    store = ActivitySnapshotStore(tmp_path / "state.sqlite")
    previous_week = dt(2026, 8, 7, 10)
    current_week = dt(2026, 8, 14, 10)

    assert store.newly_observed_ids({1, 2}, previous_week) == (
        frozenset({1, 2}),
        False,
    )
    assert store.newly_observed_ids({1, 2, 3}, current_week) == (
        frozenset({3}),
        True,
    )
