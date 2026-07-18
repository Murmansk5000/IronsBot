from typing import Any

from nonebot import logger

from ironsbot.services.activity.runtime_keys import ACTIVITY_REMINDER_REFRESH_KEY
from ironsbot.shared.messaging.push_subscription_models import (
    CRON_TIME_PREFERENCE,
)
from ironsbot.shared.runtime.refresh import refresh_runtime

from . import schedules as message_schedules
from .preference_cleanup import prune_stale_push_preferences
from .push_time import (
    PushTimeOption,
)

MESSAGE_SCHEDULE_REFRESH_KEY = "messaging.schedules"


async def refresh_push_time_jobs(option: PushTimeOption) -> None:
    if option.preference_type == CRON_TIME_PREFERENCE:
        await refresh_runtime(MESSAGE_SCHEDULE_REFRESH_KEY)
        return

    await refresh_runtime(ACTIVITY_REMINDER_REFRESH_KEY)


async def register_message_schedules(scheduler: Any) -> None:
    await message_schedules.register_message_schedules(scheduler)


async def start_messaging(scheduler: Any) -> None:
    try:
        prune_result = prune_stale_push_preferences()
    except Exception:  # noqa: BLE001 - cleanup must never block bot startup
        logger.exception("startup push preference cleanup failed")
    else:
        logger.info(
            "startup push preference cleanup complete: "
            "unsubscriptions_deleted={}, time_preferences_deleted={}",
            prune_result.unsubscriptions_deleted,
            prune_result.time_preferences_deleted,
        )
    await register_message_schedules(scheduler)


__all__ = [
    "MESSAGE_SCHEDULE_REFRESH_KEY",
    "refresh_push_time_jobs",
    "register_message_schedules",
    "start_messaging",
]
