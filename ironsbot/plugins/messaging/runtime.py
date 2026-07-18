from typing import Any

from nonebot import logger

from . import schedules as message_schedules
from .preference_cleanup import prune_stale_push_preferences


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
    await message_schedules.register_message_schedules(scheduler)
