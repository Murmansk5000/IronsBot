# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot import logger, require

from ..config import plugin_config
from ._local_rank_refresh import refresh_local_rank_cache

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler


@scheduler.scheduled_job(
    "cron",
    hour=plugin_config.seer_query_cache_refresh_hour,
    minute=plugin_config.seer_query_cache_refresh_minute,
    id="custom_get_seer_info_local_rank_refresh",
    replace_existing=True,
)
async def _scheduled_local_rank_refresh() -> None:
    if not plugin_config.seer_query_cache_auto_refresh:
        return

    result = await refresh_local_rank_cache()
    logger.info(
        "local rank cache auto refresh finished: "
        f"total={result.total}, "
        f"success={result.success}, "
        f"skipped_full={result.skipped_full}, "
        f"failed={result.failed}"
    )
