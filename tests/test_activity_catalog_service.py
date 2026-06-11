from datetime import datetime
from zoneinfo import ZoneInfo

from pytest import MonkeyPatch

from ironsbot.services.activity import catalog

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
        10,
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
            "end_time": "2026-06-10 10:00:00",
            "sort_order": 3,
        },
        {
            "id": 4,
            "name": "未开始",
            "start_time": "2026-06-18 00:00:00",
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
            "start_time": "2026-06-05 10:00:00",
            "end_time": "2026-07-03 10:00:00",
            "sort_order": 1,
        }
    ]

    [activity] = catalog.build_active_activity_infos(rows, dt(2026, 6, 10, 8))

    assert activity.offer_label == "首周优惠"
    assert activity.offer_window_days == FIRST_WEEK_DAYS
    assert activity.offer_end_time == dt(2026, 6, 12, 10)
