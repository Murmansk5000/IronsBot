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
from ironsbot.services.ai.command_contracts import ai_intent_command_contracts
from ironsbot.services.help_visibility import feature_help_visible

if TYPE_CHECKING:
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.feature_policy import FeatureService


__plugin_meta__ = PluginMetadata(
    name="AI意图分析",
    description="按配置识别简短意图，并触发对应回复或功能。",
    usage="发送已配置关键词触发相应意图动作。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution(
    *, settings: Settings, features: FeatureService
) -> PluginContribution:
    """Declare configured intent actions and their visibility."""

    enabled = settings.ai.enabled and settings.ai.intent_actions_enabled
    command_contracts = ai_intent_command_contracts(settings)
    return PluginContribution(
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
                enabled=enabled,
            ),
        ),
        commands=command_contracts,
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            settings=context.settings, features=context.resources.features
        ),
    )
