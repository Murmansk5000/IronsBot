# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nonebot.log import logger

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot
    from nonebot.internal.driver import Driver

    from ironsbot.runtime.plugins import (
        AsyncHook,
        BotHook,
        NamedAsyncHook,
        NamedBotHook,
    )


@dataclass(slots=True)
class ApplicationLifecycle:
    driver: Driver
    startup_hooks: tuple[NamedAsyncHook, ...] = ()
    shutdown_hooks: tuple[NamedAsyncHook, ...] = ()
    first_bot_connect_hooks: tuple[NamedBotHook, ...] = ()
    bot_connect_hooks: tuple[NamedBotHook, ...] = ()
    bot_disconnect_hooks: tuple[NamedBotHook, ...] = ()
    connected_bot_ids: set[int] = field(default_factory=set, init=False)
    _first_bot_connected: bool = field(default=False, init=False)
    _installed: bool = field(default=False, init=False)

    def install(self) -> None:
        if self._installed:
            return

        self.driver.on_startup(self.startup)
        self.driver.on_shutdown(self.shutdown)
        self.driver.on_bot_connect(self.bot_connect)
        self.driver.on_bot_disconnect(self.bot_disconnect)
        self._installed = True

    async def startup(self) -> None:
        await self._run_async_hooks("startup", self.startup_hooks)

    async def shutdown(self) -> None:
        await self._run_async_hooks(
            "shutdown",
            tuple(reversed(self.shutdown_hooks)),
        )

    async def bot_connect(self, bot: Bot) -> None:
        self.connected_bot_ids.add(int(bot.self_id))
        if not self._first_bot_connected:
            self._first_bot_connected = True
            await self._run_bot_hooks(
                "first_bot_connect",
                self.first_bot_connect_hooks,
                bot,
            )
        await self._run_bot_hooks("bot_connect", self.bot_connect_hooks, bot)

    async def bot_disconnect(self, bot: Bot) -> None:
        try:
            await self._run_bot_hooks(
                "bot_disconnect",
                self.bot_disconnect_hooks,
                bot,
            )
        finally:
            self.connected_bot_ids.discard(int(bot.self_id))

    @staticmethod
    async def _run_async_hooks(
        phase: str,
        hooks: tuple[NamedAsyncHook, ...],
    ) -> None:
        for name, hook in hooks:
            await ApplicationLifecycle._run_async_hook(phase, name, hook)

    @staticmethod
    async def _run_bot_hooks(
        phase: str,
        hooks: tuple[NamedBotHook, ...],
        bot: Bot,
    ) -> None:
        for name, hook in hooks:
            await ApplicationLifecycle._run_bot_hook(phase, name, hook, bot)

    @staticmethod
    async def _run_async_hook(
        phase: str,
        name: str,
        hook: AsyncHook,
    ) -> None:
        try:
            await hook()
        except Exception:  # noqa: BLE001 - one owner must not block later owners
            logger.opt(exception=True).error(
                "lifecycle {} hook failed: {}",
                phase,
                name,
            )

    @staticmethod
    async def _run_bot_hook(
        phase: str,
        name: str,
        hook: BotHook,
        bot: Bot,
    ) -> None:
        try:
            await hook(bot)
        except Exception:  # noqa: BLE001 - one owner must not block later owners
            logger.opt(exception=True).error(
                "lifecycle {} hook failed: {}",
                phase,
                name,
            )


__all__ = ["ApplicationLifecycle"]
