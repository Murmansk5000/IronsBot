from nonebot import require
from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

from ironsbot.custom_plugins.common.time_config import daily_time_parts
from ironsbot.custom_plugins.feature_policy import get_superuser_ids
from ironsbot.custom_plugins.message_actions import send_broadcast_message
from ironsbot.custom_plugins.startup_ready import register_startup_check

from .config import INVALID_RECONNECT_TIME_ERROR, plugin_config
from .service import (
    headless_is_configured,
    headless_login_failure_reason,
    headless_user_id_text,
    login_headless_client,
)
from .state import mark_headless_available, mark_headless_unavailable

require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler

RECONNECT_JOB_PREFIX = "headless_reconnect_check"

__plugin_meta__ = PluginMetadata(
    name="自定义无头登录",
    description="自定义无头登录状态检查、掉线播报和定时重连",
    usage=(
        "【自定义无头登录】\n"
        "启动后检查 HEADLESS_SEER_USER_ID / HEADLESS_SEER_PASSWORD 是否登录成功。\n"
        "登录状态从在线/离线发生变化时私聊 SUPERUSERS；正常维护窗口内不播报。\n"
        "每天按 HEADLESS_NOTICE_CONFIG.reconnect_check_times "
        "检查无头状态，掉线则尝试重连。\n"
        "超级管理员可发送 /开服查询 触发开服查询和无头重连。"
    ),
)


def _build_startup_notice_message(reason: str) -> Message:
    return Message(
        plugin_config.headless_notice_config.login_notice_message.format(
            user_id=headless_user_id_text(),
            reason=reason,
        )
    )


async def _startup_check(bot: Bot) -> None:
    if not headless_is_configured():
        return

    reason = headless_login_failure_reason()
    if reason is None:
        await mark_headless_available(
            source="启动检查",
            notify=False,
        )
        return

    await mark_headless_unavailable(
        reason,
        source="启动检查",
        notify=False,
    )
    if not plugin_config.headless_notice_config.login_notice:
        return

    target_users = sorted(get_superuser_ids())
    if not target_users:
        logger.warning("headless seer failure notice has no superusers")
        return

    await send_broadcast_message(
        _build_startup_notice_message(reason),
        private_user_ids=target_users,
        bot=bot,
        action_name="headless seer failure notice",
        interval_seconds=1.2,
    )


async def _daily_reconnect_check(scheduled_time: str) -> None:
    if not headless_is_configured():
        logger.info("headless reconnect check skipped: not configured")
        return

    reason = headless_login_failure_reason()
    if reason is None:
        await mark_headless_available(
            source=f"定时检测 {scheduled_time}",
            notify=False,
        )
        return

    await mark_headless_unavailable(
        reason,
        source=f"定时检测 {scheduled_time}",
        notify=True,
    )
    try:
        user_id = await login_headless_client()
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=True).warning(
            "headless reconnect check failed at {}",
            scheduled_time,
        )
        await mark_headless_unavailable(
            str(e),
            source=f"定时重连 {scheduled_time}",
            notify=True,
        )
        return

    await mark_headless_available(
        source=f"定时重连 {scheduled_time}",
        user_id=user_id,
        notify=True,
    )


def _register_reconnect_checks() -> None:
    reconnect_times = plugin_config.headless_notice_config.parsed_reconnect_check_times
    for scheduled_time in reconnect_times:
        hour, minute = daily_time_parts(
            scheduled_time,
            error_message=INVALID_RECONNECT_TIME_ERROR,
        )
        scheduler.add_job(
            _daily_reconnect_check,
            "cron",
            id=f"{RECONNECT_JOB_PREFIX}:{scheduled_time}",
            args=[scheduled_time],
            replace_existing=True,
            hour=hour,
            minute=minute,
            second=0,
            timezone="Asia/Shanghai",
        )

    if reconnect_times:
        logger.info(
            "headless reconnect checks registered: {}",
            ", ".join(reconnect_times),
        )


register_startup_check("headless_seer_login", _startup_check)
_register_reconnect_checks()
