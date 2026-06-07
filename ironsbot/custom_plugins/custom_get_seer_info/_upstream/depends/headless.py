# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.matcher import Matcher
from nonebot.params import Depends

if TYPE_CHECKING:
    from ironsbot.plugins.headless_seer.game import SeerGame


async def _get_game_client(matcher: Matcher) -> SeerGame:
    from ironsbot.plugins.headless_seer.exception import (
        ClientNotInitializedError,
        DisconnectedError,
        NotLoggedInError,
    )
    from ironsbot.plugins.headless_seer.manager import client_manager

    try:
        return client_manager.get_client()
    except ClientNotInitializedError:
        await matcher.finish("❌ 无头客户端尚未初始化，无法使用此命令")
    except NotLoggedInError:
        await matcher.finish("❌ 无头客户端尚未登录，无法使用此命令")
    except DisconnectedError:
        await matcher.finish("❌ 无头客户端连接已断开，正在尝试重连，请稍后再试")


GameClient = Depends(_get_game_client)
