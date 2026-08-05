# SPDX-License-Identifier: GPL-3.0-or-later
"""OneBot manifest entrypoint for the unified Seer query surface."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)

from .command_catalog import command_descriptors

__plugin_meta__ = PluginMetadata(
    name="赛尔号查询",
    description="查询赛尔号玩家、精灵、刻印、榜单与活动数据。",
    usage="发送“帮助”查看当前群已开放的赛尔号查询指令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.app.composition import ApplicationResources
    from ironsbot.config.models.settings import Settings
    from ironsbot.runtime.matchers import MatcherFactory
    from ironsbot.services.operations.scheduler import Scheduler


def _install(
    registry: MatcherFactory,
    *,
    settings: Settings,
    resources: ApplicationResources,
) -> None:
    from .commands.install import install
    from .group import SeerMatcherGroup

    install(
        SeerMatcherGroup(
            registry,
            resources.seer,
            resources.features,
            resources.commands,
            settings.player_accounts,
            resources.sendpic.exact_command_texts,
        )
    )


async def _report_render_crash(
    _bot: Bot,
    *,
    settings: Settings,
    resources: ApplicationResources,
) -> None:
    from ironsbot.services.seer.render_crash_report import (
        report_previous_render_crash,
    )

    await report_previous_render_crash(
        resources.admin_notices,
        settings.bot.logging,
        settings.paths.log_file,
    )


def plugin_contribution(
    *,
    settings: Settings,
    resources: ApplicationResources,
    scheduler: Scheduler,
) -> PluginContribution:
    from ironsbot.services.seer.rank_refresh_scheduler import (
        register_local_rank_refresh_job,
        register_rank_page_refresh_jobs,
    )

    return PluginContribution(
        id="seer_query",
        features=frozenset(
            {
                Feature.SEER,
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
        commands=command_descriptors(),
        install=partial(_install, settings=settings, resources=resources),
        hooks=PluginHooks(
            startup=(
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
                    partial(
                        _report_render_crash,
                        settings=settings,
                        resources=resources,
                    ),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            settings=context.settings,
            resources=context.resources,
            scheduler=context.scheduler,
        ),
    )
