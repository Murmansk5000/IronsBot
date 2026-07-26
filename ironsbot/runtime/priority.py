# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from logging import getLogger
from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

if TYPE_CHECKING:
    from ironsbot.core.features import FeatureService, SuperuserPriorityConfig

logger = getLogger(__name__)

STATE_ENTERED_KEY = "_superuser_priority_entered"
STATE_SUPERUSER_KEY = "_superuser_priority_superuser"


@dataclass(slots=True)
class PriorityState:
    superuser_waiting: int = 0
    superuser_active: int = 0
    normal_active: int = 0


@dataclass(slots=True)
class AdminPriorityService:
    config: SuperuserPriorityConfig
    features: FeatureService
    state: PriorityState = field(default_factory=PriorityState)
    condition: asyncio.Condition = field(
        default_factory=asyncio.Condition,
        repr=False,
    )

    async def enter(self, event: Event, state: T_State) -> None:
        if not self.config.enabled:
            return

        is_priority_user = self._is_superuser_event(event)
        state[STATE_SUPERUSER_KEY] = is_priority_user
        if is_priority_user:
            await self._enter_superuser_event()
        else:
            await self._enter_normal_event()
        state[STATE_ENTERED_KEY] = True

    async def leave(self, state: T_State) -> None:
        if not self.config.enabled or not state.get(STATE_ENTERED_KEY):
            return

        async with self.condition:
            if state.get(STATE_SUPERUSER_KEY):
                self.state.superuser_active = max(
                    0, self.state.superuser_active - 1
                )
            else:
                self.state.normal_active = max(0, self.state.normal_active - 1)
            self.condition.notify_all()

    async def wait(self, event: Event | None) -> None:
        if (
            not self.config.enabled
            or event is None
            or self._is_superuser_event(event)
        ):
            return
        await self._wait_until_no_superuser()

    async def release(self, state: T_State) -> None:
        if (
            not self.config.enabled
            or not state.get(STATE_ENTERED_KEY)
            or not state.get(STATE_SUPERUSER_KEY)
        ):
            return

        async with self.condition:
            self.state.superuser_active = max(
                0, self.state.superuser_active - 1
            )
            state[STATE_ENTERED_KEY] = False
            self.condition.notify_all()

    async def _enter_superuser_event(self) -> None:
        async with self.condition:
            self.state.superuser_waiting += 1
            self.condition.notify_all()
            self.state.superuser_waiting -= 1
            self.state.superuser_active += 1
            self.condition.notify_all()

    async def _enter_normal_event(self) -> None:
        async with self.condition:
            await self._wait_until_no_superuser_locked()
            self.state.normal_active += 1

    async def _wait_until_no_superuser(self) -> None:
        async with self.condition:
            await self._wait_until_no_superuser_locked()

    async def _wait_until_no_superuser_locked(self) -> None:
        timeout = self.config.wait_timeout_seconds
        if timeout <= 0:
            while self._has_superuser_pressure():
                await self.condition.wait()
            return

        deadline = asyncio.get_running_loop().time() + timeout
        while self._has_superuser_pressure():
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                logger.debug("superuser priority wait timed out; normal event resumes")
                return
            try:
                await asyncio.wait_for(self.condition.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                logger.debug("superuser priority wait timed out; normal event resumes")
                return

    def _has_superuser_pressure(self) -> bool:
        return self.state.superuser_waiting > 0 or self.state.superuser_active > 0

    def _is_superuser_event(self, event: Event) -> bool:
        try:
            user_id = int(event.get_user_id())
        except (TypeError, ValueError):
            return False
        return self.features.is_superuser(user_id)
