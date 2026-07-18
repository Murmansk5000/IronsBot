# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import httpx

from ironsbot.app.lifecycle import ApplicationLifecycle
from ironsbot.integrations.http.activity_notice import UnityNoticeSource
from ironsbot.integrations.storage.activity import ActivitySentStore
from ironsbot.services.activity.delivery import (
    ActivityReminderDelivery,
    ActivityReminderTargets,
)
from ironsbot.services.activity.models import ActivityInfoCache
from ironsbot.services.activity.repository import load_activity_rows
from ironsbot.services.activity.service import (
    ACTIVITY_PUSH_SUBSCRIPTION_KEY,
    ActivityService,
    TargetType,
)
from ironsbot.shared.features import (
    groups_for_feature,
    users_for_feature,
    users_with_superusers,
)
from ironsbot.shared.messaging import send_broadcast_message
from ironsbot.shared.messaging.push_subscription_models import (
    ACTIVITY_LEAD_HOURS_PREFERENCE,
    CRON_TIME_PREFERENCE,
)
from ironsbot.shared.messaging.push_subscription_store import (
    PushUnsubscribeStore,
)
from ironsbot.shared.promotions import append_fire_manual_ad_for_group

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

    from ironsbot.config.models.activity import ActivityConfig
    from ironsbot.plugins.messaging.push_time import PushTimeOption
    from ironsbot.runtime.plugins import PluginDefinition

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SEERAPI_DB_NAME = "seerapi"
ACTIVITY_INFO_CACHE_TTL = timedelta(seconds=60)
SOON_ENDING_THRESHOLD = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class ActivityComponent:
    service: ActivityService
    http_client: httpx.Client

    async def close(self) -> None:
        self.http_client.close()


async def refresh_push_time_jobs(
    option: PushTimeOption,
    *,
    scheduler: Any,
    activity_service: ActivityService,
) -> None:
    if option.preference_type == CRON_TIME_PREFERENCE:
        from ironsbot.plugins.messaging.schedules import (
            register_message_schedules,
        )

        await register_message_schedules(scheduler)
        return

    await activity_service.schedule_reminders(scheduler)


def build_activity_component(
    config: ActivityConfig,
    *,
    push_subscription_path: str,
) -> ActivityComponent:
    from ironsbot.integrations.db_registry import db_manager

    http_client = httpx.Client(
        headers={"User-Agent": "IronsBot activity reminder"},
        timeout=config.notice_timeout_seconds,
    )
    notice_source = UnityNoticeSource(http_client)
    sent_store = ActivitySentStore(config.cache_path)
    preference_store = PushUnsubscribeStore(push_subscription_path)

    def load_rows():
        return load_activity_rows(
            db_manager.get_session,
            database_name=SEERAPI_DB_NAME,
            only_shown=config.only_shown,
        )

    def preference_values():
        return (
            preference.value
            for preference in preference_store.all_time_preferences(
                subscription_key=ACTIVITY_PUSH_SUBSCRIPTION_KEY,
                preference_type=ACTIVITY_LEAD_HOURS_PREFERENCE,
            )
        )

    def preference_for_target(
        target_type: TargetType,
        target_id: int,
    ) -> str | None:
        return preference_store.get_time_preference(
            target_type,
            target_id,
            ACTIVITY_PUSH_SUBSCRIPTION_KEY,
            ACTIVITY_LEAD_HOURS_PREFERENCE,
        )

    def targets() -> ActivityReminderTargets:
        return ActivityReminderTargets(
            group_ids=tuple(groups_for_feature(ACTIVITY_PUSH_SUBSCRIPTION_KEY)),
            private_user_ids=tuple(
                users_with_superusers(
                    users_for_feature(ACTIVITY_PUSH_SUBSCRIPTION_KEY)
                )
            ),
        )

    async def broadcast(delivery: ActivityReminderDelivery) -> bool:
        summary = await send_broadcast_message(
            delivery.message,
            group_ids=delivery.group_ids,
            private_user_ids=delivery.private_user_ids,
            action_name=delivery.action_name,
            interval_seconds=1.2,
            message_limiter=append_fire_manual_ad_for_group,
            subscription_key=ACTIVITY_PUSH_SUBSCRIPTION_KEY,
        )
        return bool(summary.succeeded)

    service = ActivityService(
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
    return ActivityComponent(service=service, http_client=http_client)


def build_application_lifecycle(
    driver: Driver,
    definitions: tuple[PluginDefinition, ...],
) -> ApplicationLifecycle:
    return ApplicationLifecycle(
        driver=driver,
        startup_hooks=tuple(
            hook
            for definition in definitions
            for hook in definition.hooks.startup
        ),
        shutdown_hooks=tuple(
            hook
            for definition in definitions
            for hook in definition.hooks.shutdown
        ),
        first_bot_connect_hooks=tuple(
            hook
            for definition in definitions
            for hook in definition.hooks.first_bot_connect
        ),
        bot_connect_hooks=tuple(
            hook
            for definition in definitions
            for hook in definition.hooks.bot_connect
        ),
        bot_disconnect_hooks=tuple(
            hook
            for definition in definitions
            for hook in definition.hooks.bot_disconnect
        ),
    )


__all__ = [
    "ActivityComponent",
    "build_activity_component",
    "build_application_lifecycle",
    "refresh_push_time_jobs",
]
