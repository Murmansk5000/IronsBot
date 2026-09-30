from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pytest import MonkeyPatch

from ironsbot.services.activity import catalog
from ironsbot.services.activity.planning import build_scheduled_reminders

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
FIRST_WEEK_DAYS = 7


def dt(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ)


def test_parse_datetime_accepts_common_input_shapes() -> None:
    assert catalog.parse_datetime("2026-06-12T10:00:00Z") == dt(
        2026,
        6,
        12,
        18,
    )
    assert catalog.parse_datetime("2026-06-12 10:00:00") == dt(
        2026,
        6,
        12,
        18,
    )
    assert catalog.parse_datetime("") is None
    assert catalog.parse_datetime("not a date") is None


def test_build_active_activity_infos_filters_and_sorts_rows(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(catalog, "offer_blocks", lambda _activity, _now: [])
    rows = [
        {
            "id": 2,
            "name": "后结束",
            "start_time": "2026-06-01 00:00:00",
            "end_time": "2026-06-20 10:00:00",
            "sort_order": 2,
        },
        {
            "id": 1,
            "name": "先结束",
            "start_time": "2026-06-01 00:00:00",
            "end_time": "2026-06-12 10:00:00",
            "sort_order": 1,
        },
        {
            "id": 3,
            "name": "已结束",
            "start_time": "2026-06-01 00:00:00",
            "end_time": "2026-06-09 10:00:00",
            "sort_order": 3,
        },
        {
            "id": 4,
            "name": "未开始",
            "start_time": "2026-06-18 08:00:00",
            "end_time": "2026-06-20 10:00:00",
            "sort_order": 4,
        },
    ]

    activities = catalog.build_active_activity_infos(rows, dt(2026, 6, 11, 8))

    assert [activity.activity_id for activity in activities] == [1, 2]


def test_build_active_activity_infos_enriches_offer_fields(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        catalog,
        "offer_blocks",
        lambda _activity, _now: ["首周优惠截止至6月12日 10:00"],
    )
    rows = [
        {
            "id": 1,
            "name": "审判天使",
            "start_time": "2026-06-05 02:00:00",
            "end_time": "2026-07-03 02:00:00",
            "sort_order": 1,
        }
    ]

    [activity] = catalog.build_active_activity_infos(rows, dt(2026, 6, 10, 8))

    assert activity.offer_label == "首周优惠"
    assert activity.offer_window_days == FIRST_WEEK_DAYS
    assert activity.offer_end_time == dt(2026, 6, 12, 10)


def test_published_utc_activity_times_schedule_first_week_reminder() -> None:
    rows = [
        {
            "id": 483,
            "name": "宿命的对决",
            "start_time": "2026-09-24 02:00:00.000000",
            "end_time": "2026-10-23 02:00:00.000000",
            "sort_order": 1,
        }
    ]
    now = dt(2026, 9, 30, 12)
    [activity] = catalog.build_active_activity_infos(
        rows,
        now,
        notice_text="◇「宿命的对决」首周优惠",
    )
    reminders = build_scheduled_reminders(
        [activity],
        now,
        lead_hours=[1],
        grace=timedelta(minutes=15),
        soon_ending_threshold=timedelta(days=7),
    )

    assert activity.start_time == dt(2026, 9, 24, 10)
    assert activity.end_time == dt(2026, 10, 23, 10)
    assert [reminder.send_time for reminder in reminders] == [dt(2026, 10, 1, 9)]
