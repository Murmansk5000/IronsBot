# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002
from nonebot.message import event_postprocessor, event_preprocessor
from nonebot.typing import T_State  # noqa: TC002

if TYPE_CHECKING:
    from ironsbot.runtime.matchers import MatcherRegistry
    from ironsbot.runtime.priority import AdminPriorityService


def install(
    _registry: MatcherRegistry,
    service: AdminPriorityService,
) -> None:
    async def leave(_event: Event, state: T_State) -> None:
        await service.leave(state)

    event_preprocessor(service.enter)
    event_postprocessor(leave)
