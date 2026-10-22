# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.plugin_install import PluginContribution, PluginHooks

if TYPE_CHECKING:
    from ironsbot.core.platform import BotAccountRef
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.operations.scheduler import Scheduler


async def check_headless_on_connect(
    _account: BotAccountRef, *, service: HeadlessService
) -> None:
    await service.check_on_connect()


def plugin_contribution(
    *,
    scheduler: Scheduler,
    service: HeadlessService,
) -> PluginContribution:
    """Declare reconnect scheduling and the initial connection health check."""

    return PluginContribution(
        id="headless_notice",
        hooks=PluginHooks(
            startup=(
                (
                    "headless_reconnect_jobs",
                    partial(service.register_reconnect_jobs, scheduler),
                ),
            ),
            first_bot_connect=(
                (
                    "headless_seer_check",
                    partial(check_headless_on_connect, service=service),
                ),
            ),
        ),
    )
