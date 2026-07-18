# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002
from nonebot.message import event_postprocessor, event_preprocessor
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.services.admin_priority import enter_priority_gate, leave_priority_gate

if TYPE_CHECKING:
    from ironsbot.runtime.matchers import MatcherRegistry


async def _enter_priority_gate(event: Event, state: T_State) -> None:
    await enter_priority_gate(event, state)


async def _leave_priority_gate(_event: Event, state: T_State) -> None:
    await leave_priority_gate(state)


def install(_registry: MatcherRegistry) -> None:
    event_preprocessor(_enter_priority_gate)
    event_postprocessor(_leave_priority_gate)
