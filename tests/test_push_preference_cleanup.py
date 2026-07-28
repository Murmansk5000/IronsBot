from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.messaging import (
    MessageConfig,
    MessageScheduledAction,
    PushUnsubscribeConfig,
)
from ironsbot.core.features import FeatureConfig
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.messaging.service import MessagingService
from ironsbot.services.messaging.subscriptions import CRON_TIME_PREFERENCE
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

    from ironsbot.services.operations.scheduler import Scheduler


def test_cleanup_uses_current_subscription_and_time_catalogs(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "push_preferences.sqlite"
    store = PushUnsubscribeStore(data_path)
    store.unsubscribe_target("group", 2001, "daily", "text_push")
    store.unsubscribe_target("group", 2001, "removed", "text_push")
    store.set_time_preference(
        "group",
        2001,
        "daily",
        CRON_TIME_PREFERENCE,
        "22:30",
    )
    store.set_time_preference(
        "group",
        2001,
        "removed",
        CRON_TIME_PREFERENCE,
        "21:30",
    )

    async def skip_schedule_registration(
        _messaging: MessagingService,
        _scheduler: Scheduler,
    ) -> None:
        return None

    monkeypatch.setattr(
        MessagingService,
        "register_schedules",
        skip_schedule_registration,
    )

    runtime = build_test_runtime(
        feature_config=FeatureConfig(group_policy={"2001": ["text_push"]})
    )
    messaging = MessagingService(
        MessageConfig(
            push_unsubscribe=PushUnsubscribeConfig(data_path=str(data_path)),
            schedules=[
                MessageScheduledAction(
                    id="daily",
                    message="每日提醒",
                    hour=23,
                    minute=0,
                )
            ],
        ),
        ActivityConfig(),
        store,
        runtime.features,
        runtime.delivery,
        lambda _target_type, _target_id: [],
    )
    asyncio.run(messaging.start(cast("Scheduler", object())))

    assert store.target_unsubscribed_keys("group", 2001) == {"daily"}
    assert (
        store.get_time_preference(
            "group",
            2001,
            "daily",
            CRON_TIME_PREFERENCE,
        )
        == "22:30"
    )
