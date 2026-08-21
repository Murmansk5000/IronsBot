# SPDX-License-Identifier: GPL-3.0-or-later
"""无头客户端状态推送主题。"""

from typing import Final

from nonebot import logger, require

ENABLE: bool = True

try:
    require("ironsbot.plugins.push")
except Exception:  # noqa: BLE001
    # 推送插件是可选依赖；无头客户端本身不应因推送插件缺失而无法加载。
    ENABLE = False
else:
    from ironsbot.plugins.push.service import (
        register_topic as _register_topic,
    )
    from ironsbot.plugins.push.service import (
        send_to_topic,
    )


LOGIN_TOPIC_ID: Final[str] = "headless_seer_login"
DISCONNECT_TOPIC_ID: Final[str] = "headless_seer_disconnect"
SERVER_MAINTENANCE_TOPIC_ID: Final[str] = "headless_seer_maintenance"

LOGIN_TOPIC_NAME: Final[str] = "无头客户端登录成功"
DISCONNECT_TOPIC_NAME: Final[str] = "无头客户端断开连接"
SERVER_MAINTENANCE_TOPIC_NAME: Final[str] = "无头客户端收到维护通知"

LOGIN_TOPIC_DESCRIPTION: Final[str] = "无头客户端成功登录游戏服务器时推送通知"
DISCONNECT_TOPIC_DESCRIPTION: Final[str] = "无头客户端与游戏服务器断开连接时推送通知"
SERVER_MAINTENANCE_TOPIC_DESCRIPTION: Final[str] = (
    "无头客户端收到游戏服务器维护通知时推送通知"
)

# 兼容按「PUSH_TOPIC_*」命名引用主题的调用方。
PUSH_TOPIC_LOGIN_ID: Final[str] = LOGIN_TOPIC_ID
PUSH_TOPIC_DISCONNECT_ID: Final[str] = DISCONNECT_TOPIC_ID
PUSH_TOPIC_SERVER_MAINTENANCE_ID: Final[str] = SERVER_MAINTENANCE_TOPIC_ID


def _register_topics() -> None:
    if not ENABLE:
        return

    for topic_id, name, description in (
        (LOGIN_TOPIC_ID, LOGIN_TOPIC_NAME, LOGIN_TOPIC_DESCRIPTION),
        (DISCONNECT_TOPIC_ID, DISCONNECT_TOPIC_NAME, DISCONNECT_TOPIC_DESCRIPTION),
        (
            SERVER_MAINTENANCE_TOPIC_ID,
            SERVER_MAINTENANCE_TOPIC_NAME,
            SERVER_MAINTENANCE_TOPIC_DESCRIPTION,
        ),
    ):
        _register_topic(
            topic_id,
            name=name,
            description=description,
            allow_subscribe=True,
            enabled=True,
        )


async def _notify(topic_id: str, content: str) -> None:
    if not ENABLE:
        return

    try:
        await send_to_topic(topic_id, content)
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).error(
            f"推送无头客户端主题通知失败（主题 '{topic_id}'）"
        )


async def notify_login_success() -> None:
    """推送无头客户端登录成功通知。"""
    await _notify(LOGIN_TOPIC_ID, "✅无头客户端登录成功")


async def notify_disconnect() -> None:
    """推送无头客户端断开连接通知。"""
    await _notify(DISCONNECT_TOPIC_ID, "⚠️无头客户端已断开连接")


async def notify_server_maintenance(timestamp: int) -> None:
    """推送无头客户端收到 41457 服务器维护通知。"""
    import math
    import time

    if not timestamp or timestamp > 1000000000:
        return

    now = time.time()
    time_diff = timestamp - now
    minutes = math.floor(time_diff // 60)
    await _notify(
        SERVER_MAINTENANCE_TOPIC_ID,
        f"🚨无头客户端收到服务器维护通知，服务器将在{minutes}分钟后关闭",
    )


_register_topics()
