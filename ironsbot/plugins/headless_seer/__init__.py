# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot import get_driver, logger

from .config import get_headless_config, get_headless_credentials
from .manager import client_manager

_driver = get_driver()


@_driver.on_startup
async def _on_startup() -> None:
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
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).error("无头客户端登录失败")


@_driver.on_shutdown
async def _on_shutdown() -> None:
    client_manager.shutdown()
