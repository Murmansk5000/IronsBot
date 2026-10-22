# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import HelpEntry, PluginContribution, PluginHooks
from ironsbot.services.activity.command_contracts import activity_command_contracts

if TYPE_CHECKING:
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.operations.scheduler import Scheduler


def plugin_contribution(
    *, service: ActivityService, scheduler: Scheduler
) -> PluginContribution:
    """Declare activity commands and reminder scheduling."""

    return PluginContribution(
        id="activity",
        features=frozenset({Feature.SEER_ACTIVITY_QUERY, Feature.SEER_ACTIVITY_PUSH}),
        help=HelpEntry(
            name="活动结束提醒",
            description="读取活动结束时间并提前提醒即将结束的活动",
            group="message",
            order=10,
            notes=("自动提醒时间由 activity.lead_hours 配置。",),
        ),
        commands=activity_command_contracts(),
        hooks=PluginHooks(
            startup=(
                (
                    "activity_reminder_jobs",
                    partial(service.register_jobs, scheduler),
                ),
            ),
        ),
    )
