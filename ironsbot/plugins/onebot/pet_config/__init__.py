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
from ironsbot.services.help_visibility import feature_help_visible
from ironsbot.services.pet_config_commands import (
    pet_config_command_contracts,
)

__plugin_meta__ = PluginMetadata(
    name="精灵配置",
    description="查询本地收录的精灵配置图。",
    usage="发送“精灵名配置”或“配置精灵名”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

if TYPE_CHECKING:
    from ironsbot.config.models.pet_config import PetConfigConfig
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.feature_policy import FeatureService


def plugin_contribution(
    *,
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
        commands=pet_config_command_contracts(
            enabled=config.enabled, image_commands=image_command_texts
        ),
    )


def _is_visible(
    context: CommandContext,
    *,
    features: FeatureService,
    enabled: bool,
) -> bool:
    return feature_help_visible(
        context,
        features=features,
        feature=Feature.PET_CONFIG.value,
        enabled=enabled,
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            features=context.resources.features,
            config=context.settings.pet_config,
            image_command_texts=context.resources.sendpic.exact_command_texts,
        ),
    )
