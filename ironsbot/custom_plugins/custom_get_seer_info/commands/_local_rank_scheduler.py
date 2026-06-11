# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot import get_driver, logger, require

from ..config import get_local_rank_config
from ._local_rank_refresh import refresh_local_rank_cache

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

driver = get_driver()


async def _scheduled_local_rank_refresh() -> None:
    if not get_local_rank_config().auto_refresh:
        return

    result = await refresh_local_rank_cache()
    logger.info(
        "local rank cache auto refresh finished: "
        f"total={result.total}, "
        f"success={result.success}, "
        f"skipped_full={result.skipped_full}, "
        f"failed={result.failed}"
    )

@driver.on_startup
async def register_local_rank_refresh_job() -> None:
    local_rank_config = get_local_rank_config()
    scheduler.add_job(
        _scheduled_local_rank_refresh,
        "cron",
        hour=local_rank_config.refresh_hour,
        minute=local_rank_config.refresh_minute,
        id="custom_get_seer_info_local_rank_refresh",
        replace_existing=True,
    )
