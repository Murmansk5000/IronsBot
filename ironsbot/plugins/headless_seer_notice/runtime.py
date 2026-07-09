# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from nonebot import get_driver, require
from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.log import logger

from ironsbot.services.headless_seer_notice.config import (
    INVALID_RECONNECT_TIME_ERROR,
    get_headless_notice_config,
)
from ironsbot.services.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.shared.config.time import daily_time_parts
from ironsbot.shared.features import get_superuser_ids
from ironsbot.shared.plugin_runtime.startup_ready import register_startup_check
from ironsbot.shared.scheduler import JobRegistry

RECONNECT_JOB_PREFIX = "headless_reconnect_check:"
_headless_notice_runtime_state = {"registered": False}


def _build_startup_notice_message(reason: str) -> Message:
    from ironsbot.services.headless_seer_notice.service import headless_user_id_text

    notice_config = get_headless_notice_config()
    return Message(
        notice_config.login_notice_message.format(
            user_id=headless_user_id_text(),
            reason=reason,
        )
    )


async def _startup_check(bot: Bot) -> None:
    from ironsbot.services.headless_seer_notice.service import (
        headless_is_configured,
        headless_login_failure_reason,
    )
    from ironsbot.shared.messaging import send_broadcast_message

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
    if not get_headless_notice_config().login_notice:
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
        subscription_key="headless_seer_notice",
    )


async def _daily_reconnect_check(scheduled_time: str) -> None:
    from ironsbot.services.headless_seer_notice.service import (
        headless_is_configured,
        headless_login_failure_reason,
        login_headless_client,
    )

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


def _register_reconnect_checks(scheduler: Any) -> None:
    reconnect_times = get_headless_notice_config().parsed_reconnect_check_times
    registry = JobRegistry(scheduler, prefix=RECONNECT_JOB_PREFIX)
    for scheduled_time in reconnect_times:
        hour, minute = daily_time_parts(
            scheduled_time,
            error_message=INVALID_RECONNECT_TIME_ERROR,
        )
        registry.add(
            _daily_reconnect_check,
            "cron",
            job_id=scheduled_time,
            args=[scheduled_time],
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


def _setup_headless_notice_runtime(driver: Any, scheduler: Any) -> None:
    if _headless_notice_runtime_state["registered"]:
        return

    register_startup_check("headless_seer_login", _startup_check)

    @driver.on_startup
    async def register_reconnect_checks() -> None:
        _register_reconnect_checks(scheduler)

    _headless_notice_runtime_state["registered"] = True


def setup_headless_notice_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_headless_notice_runtime(get_driver(), scheduler)


__all__ = ["setup_headless_notice_runtime"]
