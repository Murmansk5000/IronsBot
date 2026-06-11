# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from nonebot import logger
from nonebot.adapters import Event  # noqa: TC002
from nonebot.message import event_postprocessor, event_preprocessor
from nonebot.plugin import PluginMetadata
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.shared.config.config import Config, get_shared_config
from ironsbot.shared.features import is_superuser

__plugin_meta__ = PluginMetadata(
    name="超级管理员优先级",
    description="超级管理员事件优先处理，普通用户事件在超级管理员活跃时等待",
    usage=(
        "启用 SUPERUSER_PRIORITY 后，超级管理员消息会优先放行；"
        "普通用户新事件会在超级管理员等待或执行期间暂停。"
    ),
    config=Config,
    supported_adapters={"~onebot.v11"},
)

STATE_ENTERED_KEY = "_superuser_priority_entered"
STATE_SUPERUSER_KEY = "_superuser_priority_superuser"


@dataclass(slots=True)
class PriorityState:
    superuser_waiting: int = 0
    superuser_active: int = 0
    normal_active: int = 0


plugin_config = get_shared_config()
_state = PriorityState()
_condition = asyncio.Condition()


@event_preprocessor
async def _enter_priority_gate(event: Event, state: T_State) -> None:
    if not plugin_config.superuser_priority:
        return

    is_priority_user = _is_superuser_event(event)
    state[STATE_SUPERUSER_KEY] = is_priority_user

    if is_priority_user:
        await _enter_superuser_event()
    else:
        await _enter_normal_event()

    state[STATE_ENTERED_KEY] = True


@event_postprocessor
async def _leave_priority_gate(_event: Event, state: T_State) -> None:
    if not plugin_config.superuser_priority:
        return
    if not state.get(STATE_ENTERED_KEY):
        return

    is_priority_user = bool(state.get(STATE_SUPERUSER_KEY))
    async with _condition:
        if is_priority_user:
            _state.superuser_active = max(0, _state.superuser_active - 1)
        else:
            _state.normal_active = max(0, _state.normal_active - 1)
        _condition.notify_all()


async def wait_for_superuser_priority(event: Event | None) -> None:
    """Checkpoint for long custom handlers before they send a response."""
    if not plugin_config.superuser_priority or event is None:
        return
    if _is_superuser_event(event):
        return

    await _wait_until_no_superuser()


async def release_superuser_priority(state: T_State) -> None:
    """Release the priority gate early for long-running superuser jobs."""
    if not plugin_config.superuser_priority:
        return
    if not state.get(STATE_ENTERED_KEY):
        return
    if not state.get(STATE_SUPERUSER_KEY):
        return

    async with _condition:
        _state.superuser_active = max(0, _state.superuser_active - 1)
        state[STATE_ENTERED_KEY] = False
        _condition.notify_all()


async def _enter_superuser_event() -> None:
    async with _condition:
        _state.superuser_waiting += 1
        _condition.notify_all()
        _state.superuser_waiting = max(0, _state.superuser_waiting - 1)
        _state.superuser_active += 1
        _condition.notify_all()


async def _enter_normal_event() -> None:
    async with _condition:
        await _wait_until_no_superuser_locked()
        _state.normal_active += 1


async def _wait_until_no_superuser() -> None:
    async with _condition:
        await _wait_until_no_superuser_locked()


async def _wait_until_no_superuser_locked() -> None:
    timeout = plugin_config.superuser_priority_wait_timeout_seconds
    if timeout <= 0:
        while _has_superuser_pressure():
            await _condition.wait()
        return

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while _has_superuser_pressure():
        remaining = deadline - loop.time()
        if remaining <= 0:
            logger.debug("superuser priority wait timed out; normal event resumes")
            return
        try:
            await asyncio.wait_for(_condition.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            logger.debug("superuser priority wait timed out; normal event resumes")
            return


def _has_superuser_pressure() -> bool:
    return _state.superuser_waiting > 0 or _state.superuser_active > 0


def _is_superuser_event(event: Event) -> bool:
    try:
        user_id = int(event.get_user_id())
    except (TypeError, ValueError):
        return False
    return is_superuser(user_id)
