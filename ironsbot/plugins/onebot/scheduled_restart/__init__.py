# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.plugin_install import PluginContribution, PluginHooks

if TYPE_CHECKING:
    from ironsbot.services.operations.scheduled_restart import ScheduledRestartService
    from ironsbot.services.operations.scheduler import Scheduler


def plugin_contribution(
    *,
    scheduler: Scheduler,
    service: ScheduledRestartService,
) -> PluginContribution:
    """Declare the configured scheduled process restart hook."""

    return PluginContribution(
        id="scheduled_restart",
        hooks=PluginHooks(
            startup=(
                (
                    "scheduled_restart_jobs",
                    partial(service.register_jobs, scheduler),
                ),
            ),
        ),
    )
