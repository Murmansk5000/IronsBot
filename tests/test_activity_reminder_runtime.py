from collections.abc import Callable
from pathlib import Path

import nonebot
from pytest import MonkeyPatch

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.plugins import activity
from ironsbot.plugins.activity import runtime as activity_runtime
from ironsbot.services.activity.delivery import ActivityReminderTargets
from ironsbot.shared.messaging.push_subscriptions import (
    ACTIVITY_LEAD_HOURS_PREFERENCE,
    PushUnsubscribeStore,
)
from tests.helpers.config import stub_app_config


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_activity_reminder_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        activity_runtime._activity_reminder_runtime_state,
        "registered",
        registered_state,
    )
    monkeypatch.setitem(
        activity_runtime._activity_reminder_runtime_state,
        "scheduler",
        None,
    )
    driver = FakeDriver()
    scheduler = object()

    activity_runtime._setup_activity_reminder_runtime(driver, scheduler)
    activity_runtime._setup_activity_reminder_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1
    assert activity_runtime._activity_reminder_runtime_state["scheduler"] is scheduler


def test_register_activity_reminder_jobs_installs_startup_and_daily_scans(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        activity_runtime,
        "get_activity_config",
        lambda: ActivityConfig(enabled=True),
    )

    activity_runtime.register_activity_reminder_jobs(scheduler)

    assert [job["id"] for job in scheduler.jobs] == [
        "activity_reminder_startup_scan",
        "activity_reminder_daily_scan",
    ]


def test_load_activity_rows_resolves_session_factory_at_runtime(
    monkeypatch: MonkeyPatch,
) -> None:
    session_factory = object()
    calls: list[tuple[object, str, bool]] = []

    def fake_load_activity_rows(
        raw_session_factory: object,
        *,
        database_name: str,
        only_shown: bool,
    ) -> list[dict[str, int]]:
        calls.append((raw_session_factory, database_name, only_shown))
        return [{"id": 1}]

    monkeypatch.setattr(
        activity,
        "_activity_db_session_factory",
        lambda: session_factory,
    )
    monkeypatch.setattr(
        activity,
        "get_activity_config",
        lambda: ActivityConfig(only_shown=False),
    )
    monkeypatch.setattr(
        activity,
        "load_activity_rows",
        fake_load_activity_rows,
    )

    assert activity._load_activity_rows() == [{"id": 1}]
    assert calls == [(session_factory, activity.SEERAPI_DB_NAME, False)]


def test_activity_lead_hour_overrides_filter_targets(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")
    store.set_time_preference(
        "group",
        1001,
        activity_runtime.ACTIVITY_PUSH_SUBSCRIPTION_KEY,
        ACTIVITY_LEAD_HOURS_PREFERENCE,
        "24,3,1",
    )
    store.set_time_preference(
        "private",
        2001,
        activity_runtime.ACTIVITY_PUSH_SUBSCRIPTION_KEY,
        ACTIVITY_LEAD_HOURS_PREFERENCE,
        "3",
    )

    monkeypatch.setattr(activity_runtime, "_activity_push_store", lambda: store)
    monkeypatch.setattr(
        activity_runtime,
        "get_activity_config",
        lambda: stub_app_config(
            activity_config=ActivityConfig(lead_hours=[11, 1])
        ).activity,
    )
    monkeypatch.setattr(
        activity_runtime,
        "activity_reminder_targets",
        lambda: ActivityReminderTargets(
            group_ids=(1001, 1002),
            private_user_ids=(2001,),
        ),
    )

    assert activity_runtime._configured_activity_lead_hours([11, 1]) == [
        24,
        11,
        3,
        1,
    ]
    assert activity_runtime._activity_reminder_targets_for_lead(11) == (
        ActivityReminderTargets(group_ids=(1002,), private_user_ids=())
    )
    assert activity_runtime._activity_reminder_targets_for_lead(3) == (
        ActivityReminderTargets(group_ids=(1001,), private_user_ids=(2001,))
    )
