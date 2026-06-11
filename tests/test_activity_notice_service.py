from datetime import datetime
from zoneinfo import ZoneInfo

from pytest import MonkeyPatch

from ironsbot.services.activity import notice
from ironsbot.services.activity.models import ActivityInfo

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def dt(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ)


def _activity() -> ActivityInfo:
    return ActivityInfo(
        activity_id=1,
        name="审判天使",
        start_time=dt(2026, 6, 5, 10),
        end_time=dt(2026, 7, 3, 10),
        sort_order=1,
    )


def test_offer_window_from_blocks_parses_week_and_day_windows() -> None:
    assert notice.offer_window_from_blocks(["首周优惠限时开启"]) == (
        "首周优惠",
        7,
    )
    assert notice.offer_window_from_blocks(["第二周特惠开启"]) == (
        "第二周优惠",
        14,
    )
    assert notice.offer_window_from_blocks(["第三天折扣"]) == (
        "第三天优惠",
        3,
    )


def test_offer_end_time_parses_exact_deadline() -> None:
    assert notice.offer_end_time(
        _activity(),
        ["首周优惠截止至6月12日 10:00"],
    ) == dt(2026, 6, 12, 10)


def test_offer_end_time_handles_24_hour_deadline() -> None:
    assert notice.offer_end_time(
        _activity(),
        ["首周优惠截止至6月12日 24点"],
    ) == dt(2026, 6, 13, 0)


def test_offer_blocks_filters_notice_text_without_network(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        notice,
        "_fetch_unity_notice_text",
        lambda _now: (
            "◇「审判天使」\n"
            "首周优惠截止至6月12日 10:00\n"
            "2. 其他活动\n"
            "没有优惠"
        ),
    )

    blocks = notice.offer_blocks(_activity(), dt(2026, 6, 10, 8))

    assert len(blocks) == 1
    assert "审判天使" in blocks[0]
    assert "首周优惠截止至6月12日 10:00" in blocks[0]
