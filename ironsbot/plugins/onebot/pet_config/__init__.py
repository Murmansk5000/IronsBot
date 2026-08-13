# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.feature_policy import (
    event_is_feature_visible_in_help,
    feature_rule,
)
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.rules import explicit_command, startswith_or_endswith
from ironsbot.plugins.onebot.seer.query.commands.query_rules import (
    not_exact_command,
    not_rank_query,
)
from ironsbot.runtime.semantic_requests import ActionDefinition
from ironsbot.services.pet_config_commands import pet_config_command_contracts

__plugin_meta__ = PluginMetadata(
    name="精灵配置",
    description="查询本地收录的精灵配置图。",
    usage="发送“精灵名配置”或“配置精灵名”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.config.models.pet_config import PetConfigConfig
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.pet_config import PetConfigQueryService


def plugin_contribution(
    *,
    service: PetConfigQueryService,
    features: FeatureService,
    config: PetConfigConfig,
    image_command_texts: frozenset[str] = frozenset(),
) -> PluginContribution:
    return PluginContribution(
        id="pet_config",
        features=frozenset({Feature.PET_CONFIG}),
        help=HelpEntry(
            name="精灵配置",
            description="按精灵名、别名或序号发送本地收录的配置图",
            group="other",
            order=10,
            visible=partial(
                _is_visible,
                features=features,
                enabled=config.enabled,
            ),
        ),
        commands=pet_config_command_contracts(enabled=config.enabled),
        install=partial(
            install,
            service=service,
            features=features,
            enabled=config.enabled,
            image_command_texts=image_command_texts,
        ),
    )


def _is_visible(
    event: "Event",
    *,
    features: FeatureService,
    enabled: bool,
) -> bool:
    return enabled and event_is_feature_visible_in_help(
        features,
        event,
        Feature.PET_CONFIG.value,
    )


def install(
    registry: MatcherFactory,
    service: PetConfigQueryService,
    features: FeatureService,
    *,
    enabled: bool,
    image_command_texts: frozenset[str],
) -> None:
    if not enabled:
        return

    from ironsbot.plugins.onebot.seer.query.query_conversation import (
        make_query_handler,
    )

    matcher = registry.on_message(
        policy=CommandPolicy.command("pet_config", help_ids=("pet_config.query",)),
        rule=feature_rule(features, Feature.PET_CONFIG.value)
        & startswith_or_endswith(
            prefixes=("精灵配置", "配置"),
            suffixes=("配置",),
        )
        & not_rank_query
        & not_exact_command(image_command_texts)
        & explicit_command(),
        priority=registry.priority("pet_config"),
        block=True,
    )
    matcher.append_handler(
        make_query_handler(
            service.search,
            service.select,
            "请问你想查询哪只精灵的配置？",
            ActionDefinition("pet_config", "精灵配置查询"),
        )
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.pet_config,
            features=context.resources.features,
            config=context.settings.pet_config,
            image_command_texts=context.resources.sendpic.exact_command_texts,
        ),
    )
