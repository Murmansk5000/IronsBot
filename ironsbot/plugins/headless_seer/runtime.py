# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Any

from nonebot import get_driver, logger

from .config import get_headless_config, get_headless_credentials
from .manager import client_manager

_headless_seer_runtime_state = {"registered": False}


async def _login_headless_seer_on_startup() -> None:
    credentials = get_headless_credentials()
    if (
        credentials.headless_seer_user_id is None
        or credentials.headless_seer_password is None
    ):
        logger.warning("无头客户端未配置用户名或密码，跳过登录")
        return

    headless_config = get_headless_config()
    try:
        await client_manager.login(
            user_id=credentials.headless_seer_user_id,
            password=credentials.headless_seer_password,
            login_server_url=headless_config.login_server_addr,
            heartbeat_interval=headless_config.heartbeat_interval,
            reconnect_retries=headless_config.reconnect_retries,
            reconnect_delay=headless_config.reconnect_delay,
            reconnect_delay_max=headless_config.reconnect_delay_max,
        )
    except Exception:
        logger.opt(exception=True).error("无头客户端登录失败")


async def _shutdown_headless_seer() -> None:
    client_manager.shutdown()


def _setup_headless_seer_runtime(driver: Any) -> None:
    if _headless_seer_runtime_state["registered"]:
        return

    driver.on_startup(_login_headless_seer_on_startup)
    driver.on_shutdown(_shutdown_headless_seer)
    _headless_seer_runtime_state["registered"] = True


def setup_headless_seer_runtime() -> None:
    _setup_headless_seer_runtime(get_driver())


__all__ = ["setup_headless_seer_runtime"]
