import asyncio
import os
import signal
from zoneinfo import ZoneInfo

from nonebot import logger, require
from nonebot.plugin import PluginMetadata

from ironsbot.shared.config.time import daily_time_parts

from .config import INVALID_RESTART_TIME_ERROR, Config, plugin_config

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
JOB_ID = "scheduled_bot_restart"
PARENT_EXIT_WAIT_SECONDS = 5.0

__plugin_meta__ = PluginMetadata(
    name="定时重启",
    description="按环境变量配置每日固定时间重启机器人容器。",
    usage=(
        "设置 MODULES.restart.enabled=true 后启用。\n"
        'MODULES={"restart":{"enabled":true,"times":"04:30,16:10"}} '
        "时每天在这些时间点重启。"
    ),
    config=Config,
)

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler


def _target_pid() -> int:
    if not plugin_config.bot_restart_config.signal_parent:
        return os.getpid()

    parent_pid = os.getppid()
    if parent_pid > 0:
        return parent_pid

    return os.getpid()


async def _scheduled_restart(scheduled_time: str) -> None:
    grace_seconds = plugin_config.bot_restart_config.grace_seconds
    if grace_seconds > 0:
        logger.warning(
            "scheduled bot restart {} will signal process in {:.1f}s",
            scheduled_time,
            grace_seconds,
        )
        await asyncio.sleep(grace_seconds)

    current_pid = os.getpid()
    target_pid = _target_pid()
    logger.warning(
        "scheduled bot restart sending SIGTERM: "
        "time={}, current_pid={}, target_pid={}",
        scheduled_time,
        current_pid,
        target_pid,
    )
    os.kill(target_pid, signal.SIGTERM)

    if target_pid != current_pid:
        await asyncio.sleep(PARENT_EXIT_WAIT_SECONDS)
        logger.warning(
            "scheduled bot restart parent did not stop current worker yet; "
            f"sending SIGTERM to current_pid={current_pid}"
        )
        os.kill(current_pid, signal.SIGTERM)


def _register_restart_job() -> None:
    restart_config = plugin_config.bot_restart_config
    if not restart_config.enabled:
        logger.info("scheduled bot restart disabled")
        return

    restart_times = restart_config.parsed_restart_times
    for scheduled_time in restart_times:
        hour, minute = daily_time_parts(
            scheduled_time,
            error_message=INVALID_RESTART_TIME_ERROR,
        )
        scheduler.add_job(
            _scheduled_restart,
            "cron",
            id=f"{JOB_ID}:{scheduled_time}",
            args=[scheduled_time],
            replace_existing=True,
            hour=hour,
            minute=minute,
            second=0,
            timezone=LOCAL_TZ,
        )

    logger.info(
        "scheduled bot restart registered: "
        "times={}",
        ", ".join(restart_times),
    )


_register_restart_job()
