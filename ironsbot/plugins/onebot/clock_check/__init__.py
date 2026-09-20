# SPDX-License-Identifier: MIT
"""Run the configured read-only host clock diagnostic after bot connection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.plugin_install import (
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__plugin_meta__ = PluginMetadata(
    name="主机时钟检查",
    description="启动后只读检查主机时钟偏差，偏差过大时写入管理员启动通知。",
    usage="后台运行，无用户指令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution(
    *,
    startup_check: Callable[[], Awaitable[None]],
) -> PluginContribution:
    return PluginContribution(
        id="clock_startup_check",
        hooks=PluginHooks(
            first_bot_connect=(("clock_startup_check", lambda _bot: startup_check()),),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(startup_check=context.resources.clock_startup_check),
    )
