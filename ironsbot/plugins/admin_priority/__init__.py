# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot.adapters import Event  # noqa: TC002
from nonebot.message import event_postprocessor, event_preprocessor
from nonebot.plugin import PluginMetadata
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.config.models.app import AppConfig
from ironsbot.services.admin_priority import enter_priority_gate, leave_priority_gate

__plugin_meta__ = PluginMetadata(
    name="超级管理员优先级",
    description="超级管理员事件优先处理，普通用户事件在超级管理员活跃时等待",
    usage=(
        "启用 runtime.priority.enabled 后，超级管理员消息会优先放行；"
        "普通用户新事件会在超级管理员等待或执行期间暂停。"
    ),
    config=AppConfig,
    supported_adapters={"~onebot.v11"},
)


@event_preprocessor
async def _enter_priority_gate(event: Event, state: T_State) -> None:
    await enter_priority_gate(event, state)


@event_postprocessor
async def _leave_priority_gate(_event: Event, state: T_State) -> None:
    await leave_priority_gate(state)
