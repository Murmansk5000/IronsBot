# SPDX-License-Identifier: MIT
"""seer_data 数据库更新推送订阅。

注册「数据库更新」推送主题，并在 seerapi / aliases 数据库同步更新后
向订阅者推送通知。订阅关系与推送历史由「消息推送中心」插件持久化。
"""

from collections.abc import Awaitable, Callable
from typing import Final

from nonebot import logger, require

ENABLE: bool = True

try:
    require("ironsbot.plugins.push")
except:  # noqa: E722
    ENABLE = False

from ironsbot.plugins.push.service import register_topic, send_to_topic

#: 推送主题 ID（其他插件可据此引用此主题）
PUSH_TOPIC_ID: Final[str] = "seer_db_update"
#: 主题显示名称
TOPIC_NAME: Final[str] = "数据库更新"
#: 主题描述
TOPIC_DESCRIPTION: Final[str] = "赛尔号数据（seerapi / aliases）同步更新后推送通知"

#: 数据库内部名称 → 展示名称
DB_DISPLAY_NAMES: Final[dict[str, str]] = {
    "seerapi": "游戏数据",
    "aliases": "别名数据",
}

#: 已完成首次同步的数据库；首次同步（启动加载）不推送，后续更新才推送
_loaded_once: set[str] = set()


async def notify_db_update(db_name: str, display_name: str | None = None) -> None:
    """推送数据库更新通知到「数据库更新」主题的订阅者。

    Args:
        db_name: 数据库内部名称（如 ``"seerapi"``）
        display_name: 展示名称；为 None 时从 ``DB_DISPLAY_NAMES`` 查询
    """

    if display_name is None:
        display_name = DB_DISPLAY_NAMES.get(db_name, db_name)
    try:
        await send_to_topic(
            PUSH_TOPIC_ID,
            f"📢{display_name}已更新，可查询最新数据",
            dedup_key=f"seer_db_update:{db_name}",
        )
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).error(
            f"推送数据库更新通知失败（数据库 '{db_name}'）"
        )


def build_updated_hook(db_name: str) -> Callable[[], Awaitable[None]]:
    """构建数据库更新回调，供 db_sync 注册。

    首次同步（启动加载）仅记录不推送；后续同步更新时触发推送。

    Args:
        db_name: 数据库内部名称

    Returns:
        可注册到 ``db_sync.register_update_hook`` 的异步回调
    """
    if not ENABLE:
        logger.debug(f"推送插件未启用，无法推送数据库更新通知（数据库 '{db_name}'）")
        return lambda: None

    async def _hook() -> None:
        if db_name not in _loaded_once:
            _loaded_once.add(db_name)
            return
        await notify_db_update(db_name)

    return _hook


if ENABLE:
    register_topic(
        PUSH_TOPIC_ID,
        name=TOPIC_NAME,
        description=TOPIC_DESCRIPTION,
        allow_subscribe=True,
        enabled=True,
    )
