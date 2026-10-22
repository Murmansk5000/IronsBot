# SPDX-License-Identifier: MIT
"""Bind native driver callbacks to the application-owned lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nonebot.adapters import Bot  # noqa: TC002 - driver evaluates hook annotations.
from nonebot.adapters.onebot.v11 import Bot as OneBot

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

    from ironsbot.app.lifecycle import ApplicationLifecycle
    from ironsbot.integrations.onebot.connections import OneBotConnections


@dataclass(slots=True)
class NoneBotLifecycleBinding:
    driver: Driver
    lifecycle: ApplicationLifecycle
    connections: OneBotConnections
    _installed: bool = field(default=False, init=False)

    def install(self) -> None:
        if self._installed:
            return
        self.driver.on_startup(self.lifecycle.startup)
        self.driver.on_shutdown(self.lifecycle.shutdown)
        self.driver.on_bot_connect(self._connect)
        self.driver.on_bot_disconnect(self._disconnect)
        self._installed = True

    async def _connect(self, bot: Bot) -> None:
        if isinstance(bot, OneBot):
            self.connections.connect(bot)
        await self.lifecycle.bot_connect(bot)

    async def _disconnect(self, bot: Bot) -> None:
        if isinstance(bot, OneBot) and not self.connections.disconnect(bot):
            return
        await self.lifecycle.bot_disconnect(bot)
