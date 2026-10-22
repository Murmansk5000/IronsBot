# SPDX-License-Identifier: MIT
"""Bind native driver callbacks to the application-owned lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nonebot.adapters import Bot  # noqa: TC002 - driver evaluates hook annotations.
from nonebot.adapters.onebot.v11 import Bot as OneBot

from ironsbot.core.platform import BotAccountRef, Platform

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
            account = BotAccountRef(Platform.ONEBOT, bot.self_id)
            await self.lifecycle.task_owner.create(
                self.lifecycle.bot_connect(account), name="onebot.connected"
            )

    async def _disconnect(self, bot: Bot) -> None:
        if not isinstance(bot, OneBot) or not self.connections.disconnect(bot):
            return
        await self.lifecycle.task_owner.create(
            self.lifecycle.bot_disconnect(BotAccountRef(Platform.ONEBOT, bot.self_id)),
            name="onebot.disconnected",
        )
