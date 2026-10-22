# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit business contribution for the unified Seer query surface."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import HelpEntry, PluginContribution, PluginHooks
from ironsbot.services.seer.command_contracts import seer_command_contracts

if TYPE_CHECKING:
    from ironsbot.app.composition import ApplicationResources
    from ironsbot.services.operations.scheduler import Scheduler


def plugin_contribution(
    *, resources: ApplicationResources, scheduler: Scheduler
) -> PluginContribution:
    from ironsbot.services.seer.rank_refresh_scheduler import (
        register_local_rank_refresh_job,
        register_rank_page_refresh_jobs,
    )
    from ironsbot.services.seer.render_crash_report import RenderCrashReporter

    render_crash_reporter = RenderCrashReporter(resources.admin_notices)

    return PluginContribution(
        id="seer_query",
        features=frozenset(
            {
                Feature.SEER,
                Feature.PET_FLIP,
                Feature.SEER_PLAYER,
                Feature.SEER_TEAM,
                Feature.SEER_PET,
                Feature.SEER_MINTMARK,
                Feature.SEER_EQUIPMENT,
                Feature.SEER_TYPE,
                Feature.SEER_PEAK,
                Feature.SEER_AUTOCARD,
                Feature.SEER_RANK,
                Feature.SEER_DATA,
            }
        ),
        help=HelpEntry(
            name="赛尔号查询",
            description="按当前权限开放赛尔号查询子功能",
            group="seer",
            order=10,
        ),
        commands=seer_command_contracts(
            resources.player_id_resolver,
            image_commands=resources.sendpic.exact_command_texts,
        ),
        hooks=PluginHooks(
            startup=(
                ("render_crash_capture", render_crash_reporter.capture_previous),
                (
                    "local_rank_jobs",
                    partial(
                        register_local_rank_refresh_job,
                        scheduler,
                        resources.headless,
                        resources.local_rank,
                    ),
                ),
                (
                    "rank_page_jobs",
                    partial(
                        register_rank_page_refresh_jobs,
                        scheduler,
                        resources.headless,
                        resources.rank_page_refresh,
                    ),
                ),
            ),
            first_bot_connect=(
                (
                    "render_crash_report",
                    render_crash_reporter.report_previous,
                ),
            ),
        ),
    )
