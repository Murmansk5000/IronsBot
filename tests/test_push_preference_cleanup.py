from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.features import FeatureConfig
from ironsbot.config.models.messaging import (
    MessageConfig,
    MessageScheduledAction,
    PushUnsubscribeConfig,
)
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.onebot.messaging_config import (
    build_onebot_message_schedule_targets,
)
from ironsbot.integrations.onebot.scheduled_delivery import (
    OneBotScheduledMessageSender,
)
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
    conversation = ConversationRef(Platform.ONEBOT, "group", "2001")
    store.unsubscribe(conversation, "daily", "text_push")
    store.unsubscribe(conversation, "removed", "text_push")
    store.set_time_preference(
        conversation,
        "daily",
        CRON_TIME_PREFERENCE,
        "22:30",
    )
    store.set_time_preference(
        conversation,
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
    config = MessageConfig(
        push_unsubscribe=PushUnsubscribeConfig(),
        schedules=[
            MessageScheduledAction(
                id="daily",
                message="每日提醒",
                time="23:00",
            )
        ],
    )
    messaging = MessagingService(
        config,
        ActivityConfig(),
        store,
        runtime.features,
        OneBotScheduledMessageSender(runtime.delivery),
        build_onebot_message_schedule_targets(
            config,
            runtime.onebot_references,
        ),
        (lambda _conversation: [],),
    )
    asyncio.run(messaging.start(cast("Scheduler", object())))

    assert store.unsubscribed_keys(conversation) == {"daily"}
    assert (
        store.get_time_preference(
            conversation,
            "daily",
            CRON_TIME_PREFERENCE,
        )
        == "22:30"
    )
