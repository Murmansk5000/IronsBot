from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pytest import MonkeyPatch

from ironsbot.plugins.fire_manual_ad.service import FIRE_MANUAL_LINK_MESSAGE
from ironsbot.services.activity import delivery as delivery_service
from ironsbot.services.activity.delivery import (
    ActivityReminderTargets,
    activity_reminder_targets,
    build_reminder_delivery,
    filter_reminders_before_send,
    format_reminder_message,
)
from ironsbot.services.activity.models import ActivityInfo, ActivityReminder

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
GROUP_ID = 686376929
USER_ID = 1621582661
SUPERUSER_ID = 10000


def dt(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ)


def _activity(activity_id: int = 1) -> ActivityInfo:
    return ActivityInfo(
        activity_id=activity_id,
        name=f"活动 {activity_id}",
        start_time=dt(2026, 6, 1, 10),
        end_time=dt(2026, 6, 12, 10),
        sort_order=activity_id,
    )


def _reminder(activity_id: int = 1) -> ActivityReminder:
    return ActivityReminder(
        activity_id=activity_id,
        name=f"活动 {activity_id}",
        end_time=dt(2026, 6, 12, 10),
        lead_hours=1,
        send_time=dt(2026, 6, 12, 9),
    )


def test_format_reminder_message_uses_template_fields() -> None:
    message = format_reminder_message(
        1,
        [_reminder()],
        template="{activity_count} 个活动：\n{activity_list}",
    )

    assert message.startswith("1 个活动：")
    assert "活动 1" in message


def test_format_reminder_message_falls_back_on_bad_template() -> None:
    message = format_reminder_message(
        1,
        [_reminder()],
        template="{missing_field}",
        fallback_template="提前 {lead_hours} 小时\n{activity_list}",
    )

    assert message.startswith("提前 1 小时")
    assert "活动 1" in message


def test_build_reminder_delivery_skips_empty_or_targetless_payload() -> None:
    assert (
        build_reminder_delivery(
            1,
            [],
            ActivityReminderTargets(group_ids=(GROUP_ID,)),
            template="{activity_list}",
        ).status
        == "skip_empty"
    )
    assert (
        build_reminder_delivery(
            1,
            [_reminder()],
            ActivityReminderTargets(),
            template="{activity_list}",
        ).status
        == "skip_no_targets"
    )


def test_build_reminder_delivery_builds_send_payload() -> None:
    delivery = build_reminder_delivery(
        1,
        [_reminder()],
        ActivityReminderTargets(
            group_ids=(GROUP_ID,),
            private_user_ids=(USER_ID,),
        ),
        template="{activity_count} 个活动：\n{activity_list}",
    )

    assert delivery.should_send
    assert delivery.message.startswith("1 个活动：")
    assert FIRE_MANUAL_LINK_MESSAGE not in delivery.message
    assert delivery.group_ids == (GROUP_ID,)
    assert delivery.private_user_ids == (USER_ID,)
    assert delivery.action_name == "activity ending reminder 1h"


def test_activity_reminder_targets_resolves_feature_targets(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        delivery_service,
        "groups_for_feature",
        lambda feature: [GROUP_ID] if feature == "custom_activity" else [],
    )
    monkeypatch.setattr(
        delivery_service,
        "users_for_feature",
        lambda feature: [USER_ID] if feature == "custom_activity" else [],
    )
    monkeypatch.setattr(
        delivery_service,
        "users_with_superusers",
        lambda users: [*users, SUPERUSER_ID],
    )

    targets = activity_reminder_targets("custom_activity")

    assert targets.group_ids == (GROUP_ID,)
    assert targets.private_user_ids == (USER_ID, SUPERUSER_ID)


def test_filter_reminders_before_send_keeps_current_valid_reminders() -> None:
    reminder = _reminder()

    assert filter_reminders_before_send(
        [reminder],
        now=dt(2026, 6, 12, 9),
        current_activities=[_activity()],
        dispatch_tolerance=timedelta(minutes=1),
        soon_ending_threshold=timedelta(days=7),
    ) == [reminder]


def test_filter_reminders_before_send_drops_stale_or_missing_activity() -> None:
    assert filter_reminders_before_send(
        [_reminder()],
        now=dt(2026, 6, 12, 9, 2),
        current_activities=[],
        dispatch_tolerance=timedelta(minutes=1),
        soon_ending_threshold=timedelta(days=7),
    ) == []
