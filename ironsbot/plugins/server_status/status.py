# SPDX-License-Identifier: MIT
from dataclasses import dataclass

from nonebot import logger

from ironsbot.integrations.headless_seer.client import get_game_client
from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
)


@dataclass(frozen=True, slots=True)
class HeadlessStatus:
    connected: bool
    reason: str = ""


def get_headless_status() -> HeadlessStatus:
    try:
        game = get_game_client()
    except (DisconnectedError, NotLoggedInError) as e:
        return HeadlessStatus(connected=False, reason=str(e))
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("开服查询检查无头客户端状态失败")
        return HeadlessStatus(
            connected=False,
            reason="检查机器人登录状态失败",
        )

    if bool(getattr(game, "is_logged_in", False)):
        return HeadlessStatus(connected=True)

    return HeadlessStatus(
        connected=False,
        reason="无头客户端未处于已登录状态",
    )
