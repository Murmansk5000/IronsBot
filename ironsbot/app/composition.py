# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.app.lifecycle import ApplicationLifecycle

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

    from ironsbot.runtime.plugins import PluginDefinition


def build_application_lifecycle(
    driver: Driver,
    definitions: tuple[PluginDefinition, ...],
) -> ApplicationLifecycle:
    return ApplicationLifecycle(
        driver=driver,
        installers=tuple(
            installer
            for definition in definitions
            for installer in definition.hooks.installers
        ),
        startup_hooks=tuple(
            hook
            for definition in definitions
            for hook in definition.hooks.startup
        ),
        shutdown_hooks=tuple(
            hook
            for definition in definitions
            for hook in definition.hooks.shutdown
        ),
        first_bot_connect_hooks=tuple(
            hook
            for definition in definitions
            for hook in definition.hooks.first_bot_connect
        ),
        bot_connect_hooks=tuple(
            hook
            for definition in definitions
            for hook in definition.hooks.bot_connect
        ),
        bot_disconnect_hooks=tuple(
            hook
            for definition in definitions
            for hook in definition.hooks.bot_disconnect
        ),
    )


__all__ = ["build_application_lifecycle"]
