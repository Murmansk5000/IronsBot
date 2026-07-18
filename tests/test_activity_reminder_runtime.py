from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from inspect import iscoroutinefunction

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.services.activity.delivery import (
    ActivityReminderDelivery,
    ActivityReminderTargets,
)
from ironsbot.services.activity.models import ActivityInfoCache, ActivityReminder
from ironsbot.services.activity.service import ActivityService, TargetType


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def _service(
    *,
    config: ActivityConfig | None = None,
    preference_values: Iterable[str] = (),
    preference_for_target: dict[tuple[TargetType, int], str] | None = None,
    targets: ActivityReminderTargets = ActivityReminderTargets(),
) -> ActivityService:
    preferences = preference_for_target or {}

    async def broadcast(_delivery: ActivityReminderDelivery) -> bool:
        return True

    def mark_sent(
        _reminders: list[ActivityReminder],
        _sent_at: datetime,
    ) -> None:
        return

    return ActivityService(
        config=config or ActivityConfig(),
        cache=ActivityInfoCache(),
        load_rows=list,
        load_notice_text=lambda _now: "",
        cache_ttl=timedelta(minutes=1),
        soon_ending_threshold=timedelta(days=7),
        filter_unsent=lambda reminders: reminders,
        mark_sent=mark_sent,
        preference_values=lambda: preference_values,
        preference_for_target=lambda target_type, target_id: preferences.get(
            (target_type, target_id)
        ),
        targets=lambda: targets,
        broadcast=broadcast,
        now=lambda: datetime(2026, 6, 1, tzinfo=timezone.utc),
    )


def test_register_activity_reminder_jobs_installs_startup_and_daily_scans() -> None:
    scheduler = FakeScheduler()

    _service().register_jobs(scheduler)

    assert [job["id"] for job in scheduler.jobs] == [
        "activity_reminder_startup_scan",
        "activity_reminder_daily_scan",
    ]
    assert all(
        iscoroutinefunction(job["func"])
        for job in scheduler.jobs
    )


def test_activity_lead_hour_overrides_filter_targets() -> None:
    service = _service(
        config=ActivityConfig(lead_hours=[11, 1]),
        preference_values=("24,3,1", "3"),
        preference_for_target={
            ("group", 1001): "24,3,1",
            ("private", 2001): "3",
        },
        targets=ActivityReminderTargets(
            group_ids=(1001, 1002),
            private_user_ids=(2001,),
        ),
    )

    assert service._configured_lead_hours() == [24, 11, 3, 1]
    assert service._targets_for_lead(11) == ActivityReminderTargets(
        group_ids=(1002,)
    )
    assert service._targets_for_lead(3) == ActivityReminderTargets(
        group_ids=(1001,),
        private_user_ids=(2001,),
    )
