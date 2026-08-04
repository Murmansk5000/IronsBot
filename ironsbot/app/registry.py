# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.app.command_directory.seer import seer_query_commands
from ironsbot.app.external_plugins import external_install, load_external_plugin
from ironsbot.core.features import Feature
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.app.composition import ApplicationResources
    from ironsbot.config.models.settings import Settings
    from ironsbot.integrations.scheduler.facade import SchedulerFacade
    from ironsbot.runtime.matchers import MatcherRegistry


def build_plugin_registry(
    *,
    settings: Settings,
    resources: ApplicationResources,
    scheduler: SchedulerFacade,
) -> tuple[PluginContribution, ...]:
    from ironsbot.custom_plugins.pet_config import (
        plugin_definition as pet_config_definition,
    )
    from ironsbot.plugins.seer.runtime import (
        register_local_rank_refresh_job,
        register_rank_page_refresh_jobs,
    )

    config = settings
    features = resources.features
    admin_notices = resources.admin_notices
    headless = resources.headless
    local_rank_service = resources.local_rank
    rank_page_refresh_service = resources.rank_page_refresh
    seer_resources = resources.seer
    pet_config_service = resources.pet_config
    definitions: tuple[PluginContribution, ...] = ()

    def install_scheduler(_registry: MatcherRegistry) -> None:
        load_external_plugin("nonebot_plugin_apscheduler")
        from nonebot_plugin_apscheduler import scheduler as backend

        scheduler.bind(backend)

    async def report_render_crash(_bot: Bot) -> None:
        from ironsbot.services.seer.render_crash_report import (
            report_previous_render_crash,
        )

        await report_previous_render_crash(
            admin_notices,
            config.bot.logging,
            config.paths.log_file,
        )

    def install_seer_query(registry: MatcherRegistry) -> None:
        from ironsbot.plugins.seer.query.commands.install import install
        from ironsbot.plugins.seer.query.group import SeerMatcherGroup

        install(
            SeerMatcherGroup(
                registry,
                seer_resources,
                features,
                resources.commands,
                config.player_accounts,
            )
        )

    definitions = (
        PluginContribution(
            id="apscheduler",
            install=install_scheduler,
            hooks=PluginHooks(
                startup=(("scheduler", scheduler.start),),
                shutdown=(("scheduler", scheduler.shutdown),),
            ),
        ),
        PluginContribution(
            id="localstore",
            install=external_install("nonebot_plugin_localstore"),
        ),
        PluginContribution(
            id="htmlkit",
            install=external_install("nonebot_plugin_htmlkit"),
        ),
        PluginContribution(
            id="saa",
            install=external_install("nonebot_plugin_saa"),
        ),
        pet_config_definition(
            service=pet_config_service,
            features=features,
            config=config.pet_config,
        ),
        PluginContribution(
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
            commands=seer_query_commands(),
            install=install_seer_query,
            hooks=PluginHooks(
                startup=(
                    (
                        "local_rank_jobs",
                        partial(
                            register_local_rank_refresh_job,
                            scheduler,
                            headless,
                            local_rank_service,
                        ),
                    ),
                    (
                        "rank_page_jobs",
                        partial(
                            register_rank_page_refresh_jobs,
                            scheduler,
                            headless,
                            rank_page_refresh_service,
                        ),
                    ),
                ),
                first_bot_connect=(("render_crash_report", report_render_crash),),
            ),
        ),
    )
    private_contributions = resources.private_extensions.load_plugin_contributions(
        resources.private_extension_runtime
    )
    return (*definitions, *private_contributions)
