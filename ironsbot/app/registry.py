# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.app.command_directory.dynamic import ai_intent_commands
from ironsbot.app.command_directory.plugins import ai_chat_commands
from ironsbot.app.command_directory.seer import seer_query_commands
from ironsbot.app.external_plugins import external_install, load_external_plugin
from ironsbot.app.plugin_visibility import feature_help_visible
from ironsbot.core.features import Feature
from ironsbot.runtime.plugins import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
)
from ironsbot.services.messaging.bot_mention_block import BotMentionBlockService

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
    from ironsbot.plugins.ai import install as install_ai
    from ironsbot.plugins.ai.intent import install as install_ai_intent
    from ironsbot.plugins.seer.runtime import (
        register_local_rank_refresh_job,
        register_rank_page_refresh_jobs,
    )

    config = settings
    features = resources.features
    admin_notices = resources.admin_notices
    headless = resources.headless
    team_resource_service = resources.team_resource
    local_rank_service = resources.local_rank
    rank_page_refresh_service = resources.rank_page_refresh
    seer_resources = resources.seer
    pet_config_service = resources.pet_config
    ai_service = resources.ai
    bot_mention_block_service = BotMentionBlockService(
        config.messaging.command_cooldown
    )
    ai_intent_command_descriptors = ai_intent_commands(config)
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
        PluginContribution(
            id="ai_chat",
            features=frozenset({Feature.AI_CHAT, Feature.ADMIN_NOTICE}),
            help=HelpEntry(
                name="AI聊天",
                description="接入 OpenAI-compatible API 的自定义聊天插件",
                group="ai",
                order=10,
                visible=partial(
                    feature_help_visible,
                    features=features,
                    feature="ai_chat",
                    enabled=bool(config.ai.api_key.strip()),
                ),
            ),
            commands=ai_chat_commands(enabled=bool(config.ai.api_key.strip())),
            install=(
                partial(
                    install_ai,
                    service=ai_service,
                    features=features,
                    group_aliases=config.features.group_aliases,
                    bot_mention_block_service=bot_mention_block_service,
                )
                if config.ai.api_key.strip()
                else None
            ),
        ),
        PluginContribution(
            id="ai_intent",
            features=frozenset(
                {
                    Feature.AI_INTENT,
                    Feature.AI_INTENT_TEAM_RECOMMEND,
                    Feature.AI_INTENT_FIRE_MANUAL,
                }
            ),
            help=HelpEntry(
                name="AI意图分析",
                description="按配置识别简短意图，并触发对应回复或功能。",
                group="ai",
                order=20,
                visible=partial(
                    feature_help_visible,
                    features=features,
                    feature="ai_intent",
                    enabled=(
                        bool(config.ai.api_key.strip())
                        and config.ai.intent_actions_enabled
                    ),
                ),
            ),
            commands=ai_intent_command_descriptors,
            install=partial(
                install_ai_intent,
                service=ai_service,
                group_aliases=config.features.group_aliases,
                team_resource=team_resource_service,
                command_help_ids=tuple(
                    command.id for command in ai_intent_command_descriptors
                ),
            ),
        ),
    )
    private_contributions = resources.private_extensions.load_plugin_contributions(
        resources.private_extension_runtime
    )
    return (*definitions, *private_contributions)
