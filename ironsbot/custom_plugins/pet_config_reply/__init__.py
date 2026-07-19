# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.features import Feature
from ironsbot.plugins.seer.query.commands.query_rules import (
    not_fixed_image_command,
    not_rank_query,
)
from ironsbot.plugins.seer.query.group import seer_feature_rule
from ironsbot.runtime.feature_policy import event_has_feature
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.plugins import HelpEntry, PluginDefinition
from ironsbot.runtime.rules import no_reply, startswith_or_endswith

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.config.models.seer import PetConfigImageConfig
    from ironsbot.core.features import FeatureService
    from ironsbot.services.seer.pet_config import PetConfigQueryService


def plugin_definition(
    *,
    service: PetConfigQueryService,
    features: FeatureService,
    config: PetConfigImageConfig,
) -> PluginDefinition:
    return PluginDefinition(
        id="pet_config_reply",
        features=frozenset({Feature.SEER_PET_CONFIG}),
        help=HelpEntry(
            name="精灵配置",
            description="按精灵名、别名或序号发送本地收录的配置图",
            usage="雷伊配置 / 配置雷伊 / 4923配置",
            group="seer",
            order=15,
            visible=partial(
                _is_visible,
                features=features,
                enabled=config.enabled,
            ),
        ),
        install=partial(
            install,
            service=service,
            features=features,
            enabled=config.enabled,
        ),
    )


def _is_visible(
    event: Event,
    *,
    features: FeatureService,
    enabled: bool,
) -> bool:
    return enabled and event_has_feature(features, event, "seer_pet_config")


def install(
    registry: MatcherRegistry,
    service: PetConfigQueryService,
    features: FeatureService,
    *,
    enabled: bool,
) -> None:
    if not enabled:
        return

    from ironsbot.plugins.seer.query.query_conversation import (
        make_query_handler,
    )

    matcher = registry.on_message(
        policy=CommandPolicy.command("seer_pet_config"),
        rule=seer_feature_rule(features, "seer_pet_config")
        & startswith_or_endswith(
            prefixes=("精灵配置", "配置"),
            suffixes=("配置",),
        )
        & not_rank_query
        & not_fixed_image_command
        & no_reply(),
        priority=registry.priority("seer_pet_config"),
        block=True,
    )
    matcher.append_handler(
        make_query_handler(
            service.search,
            service.select,
            "请问你想查询哪只精灵的配置？",
        )
    )
