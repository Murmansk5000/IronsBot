# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import HelpEntry, PluginContribution, PluginHooks
from ironsbot.core.time import scheduled_clock_time
from ironsbot.services.help_visibility import feature_help_visible
from ironsbot.services.operations.scheduler import JobRegistry
from ironsbot.services.seer.lucky_skin_commands import (
    lucky_skin_window_command_contracts,
)

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver

_JOB_PREFIX = "lucky_skin_window:"


def plugin_contribution(
    service: LuckySkinWindowService,
    features: FeatureService,
    scheduler: Scheduler,
    resolver: PlayerIdResolver,
) -> PluginContribution:
    return PluginContribution(
        id="lucky_skin_window",
        features=frozenset({Feature.LUCKY_SKIN_WINDOW}),
        help=HelpEntry(
            name="幸运橱窗",
            description="查看绑定米米号当天幸运橱窗刷新的四个皮肤。",
            group="seer",
            order=16,
            visible=partial(_help_visible, service=service, features=features),
            notes=(
                "发送“橱窗”查看；可用“关注橱窗”或“订阅橱窗”管理星标；可在“TD”中退订每日提醒。",
            ),
        ),
        commands=lucky_skin_window_command_contracts(resolver.has_reference_choices),
        hooks=PluginHooks(
            startup=(
                (
                    "lucky_skin_window_schedule",
                    partial(_register_schedule, service, scheduler),
                ),
            ),
        ),
    )


def _help_visible(
    context: CommandContext,
    *,
    service: LuckySkinWindowService,
    features: FeatureService,
) -> bool:
    if not service.is_eligible_actor(context.actor) and not features.is_actor_superuser(
        context.actor
    ):
        return False
    return feature_help_visible(
        context,
        features=features,
        feature="lucky_skin_window",
    )


def _register_schedule(
    service: LuckySkinWindowService,
    scheduler: Scheduler,
) -> None:
    if not service.enabled:
        return
    config = service.config
    daily_time = scheduled_clock_time(
        config.time,
        error_message="invalid lucky skin window time",
    )
    JobRegistry(scheduler, prefix=_JOB_PREFIX).add(
        service.clear_previous_days,
        "cron",
        job_id="cache_cleanup",
        hour=0,
        minute=0,
        second=0,
        timezone=config.timezone,
    )
    JobRegistry(scheduler, prefix=_JOB_PREFIX).add_daily(
        service.send_daily_notifications,
        clock_time=daily_time,
        job_id="daily",
        timezone=config.timezone,
    )
