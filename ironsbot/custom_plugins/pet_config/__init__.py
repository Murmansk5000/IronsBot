# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.features import Feature
from ironsbot.plugins.seer.query.commands.query_rules import (
    not_fixed_image_command,
    not_rank_query,
)
from ironsbot.runtime.feature_policy import (
    event_is_feature_visible_in_help,
    feature_rule,
)
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.plugins import HelpEntry, PluginDefinition
from ironsbot.runtime.rules import no_reply, startswith_or_endswith

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.config.models.pet_config import PetConfigConfig
    from ironsbot.core.features import FeatureService
    from ironsbot.services.pet_config import PetConfigQueryService


def plugin_definition(
    *,
    service: PetConfigQueryService,
    features: FeatureService,
    config: PetConfigConfig,
) -> PluginDefinition:
    return PluginDefinition(
        id="pet_config",
        features=frozenset({Feature.PET_CONFIG}),
        help=HelpEntry(
            name="精灵配置",
            description="按精灵名、别名或序号发送本地收录的配置图",
            usage="雷伊配置 / 配置雷伊 / 4923配置",
            group="other",
            order=10,
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
        policy=CommandPolicy.command("pet_config"),
        rule=feature_rule(features, Feature.PET_CONFIG.value)
        & startswith_or_endswith(
            prefixes=("精灵配置", "配置"),
            suffixes=("配置",),
        )
        & not_rank_query
        & not_fixed_image_command
        & no_reply(),
        priority=registry.priority("pet_config"),
        block=True,
    )
    matcher.append_handler(
        make_query_handler(
            service.search,
            service.select,
            "请问你想查询哪只精灵的配置？",
        )
    )
