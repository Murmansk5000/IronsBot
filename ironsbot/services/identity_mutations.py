# SPDX-License-Identifier: MIT
"""Serialize committed identity changes and publication under one task owner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from ironsbot.core.tasks import run_owned_operation

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

    from ironsbot.core.tasks import TaskSpawner

T = TypeVar("T")


@dataclass(slots=True)
class IdentityMutationCoordinator:
    spawn: TaskSpawner
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def run(self, operation: Callable[[], Coroutine[Any, Any, T]]) -> T:
        async with self._lock:
            return await run_owned_operation(
                operation, spawn=self.spawn, name="identity_mutation"
            )
