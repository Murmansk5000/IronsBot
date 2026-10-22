# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.plugin_install import PluginContribution, PluginHooks
from ironsbot.services.operations.startup_delivery import send_startup_notice

if TYPE_CHECKING:
    from ironsbot.config.models.operations import StartupConfig
    from ironsbot.services.operations.startup import StartupNoticeService


def plugin_contribution(
    *,
    service: StartupNoticeService,
    config: StartupConfig,
) -> PluginContribution:
    """Declare the first-connection startup notice lifecycle hook."""

    return PluginContribution(
        id="startup_notice",
        hooks=PluginHooks(
            first_bot_connect=(
                (
                    "startup_notice",
                    lambda _account: send_startup_notice(service, config),
                ),
            ),
        ),
    )
