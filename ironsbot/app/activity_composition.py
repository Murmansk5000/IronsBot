# SPDX-License-Identifier: MIT
"""Activity reminder wiring kept out of the application composition root."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ironsbot.integrations.storage.activity import ActivitySentStore
from ironsbot.services.activity.delivery import ActivityReminderTargets
from ironsbot.services.activity.models import ActivityInfoCache
from ironsbot.services.activity.repository import ActivityRepository
from ironsbot.services.activity.service import (
    ACTIVITY_PUSH_SUBSCRIPTION_KEY,
    ActivityService,
)
from ironsbot.services.messaging.subscriptions import (
    ACTIVITY_LEAD_HOURS_PREFERENCE,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.config.models.activity import ActivityConfig
    from ironsbot.core.features import FeatureService
    from ironsbot.integrations.db_registry import DatabaseManager
    from ironsbot.integrations.http.activity_notice import UnityNoticeSource
    from ironsbot.integrations.storage.push_subscriptions import (
        PushUnsubscribeStore,
    )
    from ironsbot.services.activity.delivery import (
        ActivityReminderDelivery,
    )
    from ironsbot.services.activity.service import TargetType
    from ironsbot.services.messaging.delivery import MessageDelivery, MessageLimiter

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SEERAPI_DB_NAME = "seerapi"
ACTIVITY_INFO_CACHE_TTL = timedelta(seconds=60)
SOON_ENDING_THRESHOLD = timedelta(days=7)


def build_activity_service(  # noqa: PLR0913 - composition root
    config: ActivityConfig,
    runtime_state_path: Path,
    features: FeatureService,
    message_delivery: MessageDelivery,
    databases: DatabaseManager,
    subscriptions: PushUnsubscribeStore,
    notice_source: UnityNoticeSource,
    message_limiter: MessageLimiter,
) -> ActivityService:
    sent_store = ActivitySentStore(runtime_state_path)
    repository = ActivityRepository()

    def load_rows():
        with databases.session(SEERAPI_DB_NAME) as session:
            return repository.load(session, only_shown=config.only_shown)

    def preference_values():
        return (
            preference.value
            for preference in subscriptions.all_time_preferences(
                subscription_key=ACTIVITY_PUSH_SUBSCRIPTION_KEY,
                preference_type=ACTIVITY_LEAD_HOURS_PREFERENCE,
            )
        )

    def preference_for_target(
        target_type: TargetType,
        target_id: int,
    ) -> str | None:
        return subscriptions.get_time_preference(
            target_type,
            target_id,
            ACTIVITY_PUSH_SUBSCRIPTION_KEY,
            ACTIVITY_LEAD_HOURS_PREFERENCE,
        )

    def targets() -> ActivityReminderTargets:
        return ActivityReminderTargets(
            group_ids=tuple(
                features.groups_for_feature(ACTIVITY_PUSH_SUBSCRIPTION_KEY)
            ),
            private_user_ids=tuple(
                features.users_with_superusers(
                    features.users_for_feature(ACTIVITY_PUSH_SUBSCRIPTION_KEY)
                )
            ),
        )

    async def broadcast(reminder: ActivityReminderDelivery) -> bool:
        summary = await message_delivery.broadcast(
            reminder.message,
            group_ids=reminder.group_ids,
            private_user_ids=reminder.private_user_ids,
            action_name=reminder.action_name,
            message_limiter=message_limiter,
            subscription_key=ACTIVITY_PUSH_SUBSCRIPTION_KEY,
        )
        return bool(summary.succeeded)

    return ActivityService(
        config=config,
        cache=ActivityInfoCache(),
        load_rows=load_rows,
        load_notice_text=notice_source.fetch,
        cache_ttl=ACTIVITY_INFO_CACHE_TTL,
        soon_ending_threshold=SOON_ENDING_THRESHOLD,
        filter_unsent=sent_store.filter_unsent,
        mark_sent=sent_store.mark_sent,
        preference_values=preference_values,
        preference_for_target=preference_for_target,
        targets=targets,
        broadcast=broadcast,
        now=lambda: datetime.now(LOCAL_TZ),
    )
