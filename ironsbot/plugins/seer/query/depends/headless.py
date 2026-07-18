# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.params import Depends

if TYPE_CHECKING:
    from ironsbot.integrations.headless_seer.game import SeerGame
    from ironsbot.services.operations.headless import HeadlessService


def game_client_dependency(headless: HeadlessService) -> Any:
    from ironsbot.integrations.headless_seer.exception import (
        ClientNotInitializedError,
        DisconnectedError,
        NotLoggedInError,
    )

    async def get_game(matcher: Matcher) -> SeerGame:
        try:
            return headless.get_game()
        except ClientNotInitializedError:
            await matcher.finish("❌ 无头客户端尚未初始化，无法使用此命令")
        except NotLoggedInError:
            await matcher.finish("❌ 无头客户端尚未登录，无法使用此命令")
        except DisconnectedError:
            await matcher.finish(
                "❌ 无头客户端连接已断开，正在尝试重连，请稍后再试"
            )

    return Depends(get_game)
