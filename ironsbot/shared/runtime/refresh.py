# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable

from nonebot.log import logger

RuntimeRefreshHandler = Callable[[], Awaitable[None]]

_refresh_handlers: dict[str, RuntimeRefreshHandler] = {}


def register_runtime_refresh(name: str, handler: RuntimeRefreshHandler) -> None:
    _refresh_handlers[name] = handler


async def refresh_runtime(name: str) -> None:
    handler = _refresh_handlers.get(name)
    if handler is None:
        logger.debug("runtime refresh skipped: {} is not registered", name)
        return

    await handler()
