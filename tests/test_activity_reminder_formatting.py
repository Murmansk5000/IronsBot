import sys
import types
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

PACKAGE_NAME = "activity_reminder_formatting_for_test"
ROOT = (
    Path(__file__).resolve().parents[1]
    / "ironsbot"
    / "custom_plugins"
    / "activity_reminder"
)

package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE_NAME] = package

_MODELS_SPEC = spec_from_file_location(f"{PACKAGE_NAME}.models", ROOT / "models.py")
assert _MODELS_SPEC is not None and _MODELS_SPEC.loader is not None
_MODELS = module_from_spec(_MODELS_SPEC)
sys.modules[_MODELS_SPEC.name] = _MODELS
_MODELS_SPEC.loader.exec_module(_MODELS)

_FORMATTING_SPEC = spec_from_file_location(
    f"{PACKAGE_NAME}.formatting",
    ROOT / "formatting.py",
)
assert _FORMATTING_SPEC is not None and _FORMATTING_SPEC.loader is not None
_FORMATTING = module_from_spec(_FORMATTING_SPEC)
sys.modules[_FORMATTING_SPEC.name] = _FORMATTING
_FORMATTING_SPEC.loader.exec_module(_FORMATTING)

ActivityDeadline = _MODELS.ActivityDeadline
ActivityInfo = _MODELS.ActivityInfo
ActivityReminder = _MODELS.ActivityReminder
format_activity_line = _FORMATTING.format_activity_line
format_activity_list = _FORMATTING.format_activity_list
format_activity_period = _FORMATTING.format_activity_period
format_remaining_time = _FORMATTING.format_remaining_time


def dt(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _activity() -> ActivityInfo:
    return ActivityInfo(
        activity_id=1,
        name="审判天使",
        start_time=dt(2026, 6, 5, 10),
        end_time=dt(2026, 7, 3, 10),
        sort_order=1,
    )


def test_format_remaining_time_uses_day_hour_minute_parts() -> None:
    assert format_remaining_time(timedelta(days=2, hours=3, minutes=4)) == (
        "2天3小时4分"
    )
    assert format_remaining_time(timedelta(seconds=30)) == "0分"


def test_format_activity_period_includes_start_when_available() -> None:
    assert format_activity_period(_activity()) == "06-05 10:00 ~ 07-03 10:00"
    activity = ActivityInfo(
        activity_id=2,
        name="无开始时间活动",
        start_time=None,
        end_time=dt(2026, 6, 12, 10),
        sort_order=2,
    )
    assert format_activity_period(activity) == "结束：06-12 10:00"


def test_format_activity_line_for_current_activity() -> None:
    assert format_activity_line(
        1,
        _activity(),
        dt(2026, 6, 10, 8, 30),
        soon_only=False,
    ) == [
        "1. 审判天使：06-05 10:00 ~ 07-03 10:00 | 剩余：23天1小时30分",
    ]


def test_format_activity_line_for_soon_deadline() -> None:
    activity = _activity()
    deadline = ActivityDeadline(
        end_time=dt(2026, 6, 12, 10),
        label="首周优惠截至",
        display_end_time=True,
    )

    assert format_activity_line(
        2,
        activity,
        dt(2026, 6, 11, 9),
        soon_only=True,
        deadline=deadline,
    ) == [
        "2. 审判天使：首周优惠截至时间：06-12 10:00 | 剩余：1天1小时",
    ]


def test_format_activity_line_for_offer_without_exact_deadline() -> None:
    activity = ActivityInfo(
        activity_id=1,
        name="审判天使",
        start_time=dt(2026, 6, 5, 10),
        end_time=dt(2026, 7, 3, 10),
        sort_order=1,
        offer_label="首周优惠",
    )
    deadline = ActivityDeadline(
        end_time=dt(2026, 6, 12, 10),
        label="首周优惠",
        display_end_time=False,
    )

    assert format_activity_line(
        1,
        activity,
        dt(2026, 6, 10, 8),
        soon_only=True,
        deadline=deadline,
    ) == [
        "1. 审判天使：首周优惠见官方说明 | 活动：06-05 10:00 ~ 07-03 10:00",
    ]


def test_format_activity_list_uses_deadline_display_flag() -> None:
    reminders = [
        ActivityReminder(
            activity_id=1,
            name="银河斗技场",
            end_time=dt(2026, 6, 12, 10),
            lead_hours=1,
            send_time=dt(2026, 6, 12, 9),
        ),
        ActivityReminder(
            activity_id=2,
            name="审判天使",
            end_time=dt(2026, 6, 12, 10),
            lead_hours=1,
            send_time=dt(2026, 6, 12, 9),
            end_label="首周优惠",
            display_end_time=False,
        ),
    ]

    assert format_activity_list(reminders) == (
        "1. 银河斗技场：结束时间时间：2026-06-12 10:00\n"
        "2. 审判天使：首周优惠见官方说明"
    )
