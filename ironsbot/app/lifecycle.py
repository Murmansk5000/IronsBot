# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import TYPE_CHECKING, Any, TypeVar

from ironsbot.core.platform import BotAccountRef, Platform

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from ironsbot.core.plugin_install import (
        BotLifecycleHook,
        LifecycleHook,
        NamedBotLifecycleHook,
        NamedLifecycleHook,
        PluginContribution,
    )
    from ironsbot.services.operations.scheduler import SchedulerLifecycle

T = TypeVar("T")
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TaskOwner:
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    _draining: set[asyncio.Task[Any]] = field(
        default_factory=set, init=False, repr=False
    )

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

    def create_draining(
        self, coroutine: Coroutine[Any, Any, T], *, name: str
    ) -> asyncio.Task[T]:
        task = self.create(coroutine, name=name)
        self._draining.add(task)
        return task

    def _finished(self, task: asyncio.Task[Any]) -> None:
        self.tasks.discard(task)
        self._draining.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "owned task %s failed: error_type=%s",
                task.get_name(),
                type(error).__name__,
            )

    async def cancel_all(self) -> None:
        tasks = tuple(self.tasks)
        for task in tasks:
            if task not in self._draining:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self._draining.clear()


@dataclass(slots=True)
class ApplicationLifecycle:
    task_owner: TaskOwner = field(default_factory=TaskOwner)
    scheduler: SchedulerLifecycle | None = None
    resource_startup_hooks: tuple[NamedLifecycleHook, ...] = ()
    startup_hooks: tuple[NamedLifecycleHook, ...] = ()
    shutdown_hooks: tuple[NamedLifecycleHook, ...] = ()
    resource_shutdown_hooks: tuple[NamedLifecycleHook, ...] = ()
    first_bot_connect_hooks: tuple[NamedBotLifecycleHook, ...] = ()
    bot_connect_hooks: tuple[NamedBotLifecycleHook, ...] = ()
    bot_disconnect_hooks: tuple[NamedBotLifecycleHook, ...] = ()
    first_connection_platforms: frozenset[Platform] = frozenset(Platform)
    connected_accounts: set[BotAccountRef] = field(default_factory=set, init=False)
    _first_bot_connected: bool = field(default=False, init=False)
    _started: bool = field(default=False, init=False)
    _stopping: bool = field(default=False, init=False)
    _pending_connections: dict[BotAccountRef, bool] = field(
        default_factory=dict, init=False, repr=False
    )

    @classmethod
    def from_contributions(
        cls,
        contributions: tuple[PluginContribution, ...],
        *,
        task_owner: TaskOwner,
        scheduler: SchedulerLifecycle | None = None,
        resource_startup_hooks: tuple[NamedLifecycleHook, ...] = (),
        resource_shutdown_hooks: tuple[NamedLifecycleHook, ...] = (),
    ) -> ApplicationLifecycle:
        return cls(
            task_owner=task_owner,
            scheduler=scheduler,
            resource_startup_hooks=resource_startup_hooks,
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

    async def startup(self) -> None:
        try:
            await self._run_lifecycle_hooks(
                "resource_startup",
                self.resource_startup_hooks,
                propagate_errors=True,
            )
            await self._run_lifecycle_hooks("startup", self.startup_hooks)
            if self.scheduler is not None:
                self.scheduler.start()
        except BaseException:
            self._pending_connections.clear()
            self._stopping = True
            raise
        self._started = True
        pending, self._pending_connections = self._pending_connections, {}
        for account, connected in pending.items():
            if connected:
                self.task_owner.create(
                    self.bot_connect(account), name="account.connected"
                )

    async def shutdown(self) -> None:
        self._stopping = True
        self._pending_connections.clear()
        if self.scheduler is not None:
            await self.scheduler.shutdown()
        await self._run_lifecycle_hooks(
            "shutdown",
            tuple(reversed(self.shutdown_hooks)),
        )
        await self.task_owner.cancel_all()
        self.connected_accounts.clear()
        await self._run_lifecycle_hooks(
            "resource_shutdown",
            tuple(reversed(self.resource_shutdown_hooks)),
        )

    async def bot_connect(self, account: BotAccountRef) -> None:
        if self._stopping:
            return
        if not self._started:
            self._pending_connections[account] = True
            return
        self.connected_accounts.add(account)
        if (
            not self._first_bot_connected
            and account.platform in self.first_connection_platforms
        ):
            self._first_bot_connected = True
            await self._run_bot_hooks(
                "first_bot_connect",
                self.first_bot_connect_hooks,
                account,
            )
        await self._run_bot_hooks("bot_connect", self.bot_connect_hooks, account)

    async def bot_disconnect(self, account: BotAccountRef) -> None:
        if self._stopping:
            return
        if not self._started:
            self._pending_connections[account] = False
            return
        if account not in self.connected_accounts:
            return
        try:
            await self._run_bot_hooks(
                "bot_disconnect",
                self.bot_disconnect_hooks,
                account,
            )
        finally:
            self.connected_accounts.discard(account)

    @staticmethod
    async def _run_lifecycle_hooks(
        phase: str,
        hooks: tuple[NamedLifecycleHook, ...],
        *,
        propagate_errors: bool = False,
    ) -> None:
        for name, hook in hooks:
            await ApplicationLifecycle._run_lifecycle_hook(
                phase,
                name,
                hook,
                propagate_errors=propagate_errors,
            )

    @staticmethod
    async def _run_bot_hooks(
        phase: str,
        hooks: tuple[NamedBotLifecycleHook, ...],
        account: BotAccountRef,
    ) -> None:
        for name, hook in hooks:
            await ApplicationLifecycle._run_bot_hook(phase, name, hook, account)

    @staticmethod
    async def _run_lifecycle_hook(
        phase: str,
        name: str,
        hook: LifecycleHook,
        *,
        propagate_errors: bool = False,
    ) -> None:
        try:
            result = hook()
            if isawaitable(result):
                await result
        except Exception:
            logger.exception(
                "lifecycle %s hook failed: %s",
                phase,
                name,
            )
            if propagate_errors:
                raise

    @staticmethod
    async def _run_bot_hook(
        phase: str,
        name: str,
        hook: BotLifecycleHook,
        account: BotAccountRef,
    ) -> None:
        try:
            result = hook(account)
            if isawaitable(result):
                await result
        except Exception:
            logger.exception(
                "lifecycle %s hook failed: %s",
                phase,
                name,
            )
