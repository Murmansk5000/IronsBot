# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import TYPE_CHECKING, Any, TypeVar

from nonebot.adapters import Bot  # noqa: TC002 - driver evaluates hook annotations.
from nonebot.log import logger

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from nonebot.internal.driver import Driver

    from ironsbot.core.plugin_install import (
        BotLifecycleHook,
        LifecycleHook,
        NamedBotLifecycleHook,
        NamedLifecycleHook,
        PluginContribution,
    )

T = TypeVar("T")


class ConnectedBotIdentityError(ValueError):
    @classmethod
    def missing_self_id(cls) -> ConnectedBotIdentityError:
        return cls("connected bot has no self_id")


@dataclass(slots=True)
class TaskOwner:
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    def create(
        self,
        coroutine: Coroutine[Any, Any, T],
        *,
        name: str,
    ) -> asyncio.Task[T]:
        task = asyncio.create_task(coroutine, name=name)
        self.tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Task[Any]) -> None:
        self.tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("background task {} failed: {}", task.get_name(), error)

    async def cancel_all(self) -> None:
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()


@dataclass(slots=True)
class ApplicationLifecycle:
    driver: Driver
    task_owner: TaskOwner = field(default_factory=TaskOwner)
    startup_hooks: tuple[NamedLifecycleHook, ...] = ()
    shutdown_hooks: tuple[NamedLifecycleHook, ...] = ()
    resource_shutdown_hooks: tuple[NamedLifecycleHook, ...] = ()
    first_bot_connect_hooks: tuple[NamedBotLifecycleHook, ...] = ()
    bot_connect_hooks: tuple[NamedBotLifecycleHook, ...] = ()
    bot_disconnect_hooks: tuple[NamedBotLifecycleHook, ...] = ()
    connected_bot_ids: set[int] = field(default_factory=set, init=False)
    _first_bot_connected: bool = field(default=False, init=False)
    _installed: bool = field(default=False, init=False)

    @classmethod
    def from_contributions(
        cls,
        driver: Driver,
        contributions: tuple[PluginContribution, ...],
        *,
        task_owner: TaskOwner,
        resource_shutdown_hooks: tuple[NamedLifecycleHook, ...] = (),
    ) -> ApplicationLifecycle:
        return cls(
            driver=driver,
            task_owner=task_owner,
            startup_hooks=tuple(
                hook
                for contribution in contributions
                for hook in contribution.hooks.startup
            ),
            shutdown_hooks=tuple(
                hook
                for contribution in contributions
                for hook in contribution.hooks.shutdown
            ),
            resource_shutdown_hooks=resource_shutdown_hooks,
            first_bot_connect_hooks=tuple(
                hook
                for contribution in contributions
                for hook in contribution.hooks.first_bot_connect
            ),
            bot_connect_hooks=tuple(
                hook
                for contribution in contributions
                for hook in contribution.hooks.bot_connect
            ),
            bot_disconnect_hooks=tuple(
                hook
                for contribution in contributions
                for hook in contribution.hooks.bot_disconnect
            ),
        )

    def install(self) -> None:
        if self._installed:
            return

        self.driver.on_startup(self.startup)
        self.driver.on_shutdown(self.shutdown)
        self.driver.on_bot_connect(self._on_bot_connect)
        self.driver.on_bot_disconnect(self._on_bot_disconnect)
        self._installed = True

    async def startup(self) -> None:
        await self._run_lifecycle_hooks("startup", self.startup_hooks)

    async def shutdown(self) -> None:
        await self._run_lifecycle_hooks(
            "shutdown",
            tuple(reversed(self.shutdown_hooks)),
        )
        await self.task_owner.cancel_all()
        await self._run_lifecycle_hooks(
            "resource_shutdown",
            tuple(reversed(self.resource_shutdown_hooks)),
        )

    async def _on_bot_connect(self, bot: Bot) -> None:
        """Adapt NoneBot's typed driver hook to platform-agnostic lifecycle hooks."""

        await self.bot_connect(bot)

    async def _on_bot_disconnect(self, bot: Bot) -> None:
        """Adapt NoneBot's typed driver hook to platform-agnostic lifecycle hooks."""

        await self.bot_disconnect(bot)

    async def bot_connect(self, bot: object) -> None:
        self.connected_bot_ids.add(_bot_id(bot))
        if not self._first_bot_connected:
            self._first_bot_connected = True
            await self._run_bot_hooks(
                "first_bot_connect",
                self.first_bot_connect_hooks,
                bot,
            )
        await self._run_bot_hooks("bot_connect", self.bot_connect_hooks, bot)

    async def bot_disconnect(self, bot: object) -> None:
        try:
            await self._run_bot_hooks(
                "bot_disconnect",
                self.bot_disconnect_hooks,
                bot,
            )
        finally:
            self.connected_bot_ids.discard(_bot_id(bot))

    @staticmethod
    async def _run_lifecycle_hooks(
        phase: str,
        hooks: tuple[NamedLifecycleHook, ...],
    ) -> None:
        for name, hook in hooks:
            await ApplicationLifecycle._run_lifecycle_hook(phase, name, hook)

    @staticmethod
    async def _run_bot_hooks(
        phase: str,
        hooks: tuple[NamedBotLifecycleHook, ...],
        bot: object,
    ) -> None:
        for name, hook in hooks:
            await ApplicationLifecycle._run_bot_hook(phase, name, hook, bot)

    @staticmethod
    async def _run_lifecycle_hook(
        phase: str,
        name: str,
        hook: LifecycleHook,
    ) -> None:
        try:
            result = hook()
            if isawaitable(result):
                await result
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
        hook: BotLifecycleHook,
        bot: object,
    ) -> None:
        try:
            result = hook(bot)
            if isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - one owner must not block later owners
            logger.opt(exception=True).error(
                "lifecycle {} hook failed: {}",
                phase,
                name,
            )


def _bot_id(bot: object) -> int:
    """Read an adapter bot's stable numeric identity at the app boundary."""

    value = getattr(bot, "self_id", None)
    if value is None:
        raise ConnectedBotIdentityError.missing_self_id()
    return int(value)
