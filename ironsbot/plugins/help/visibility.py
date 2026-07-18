# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from ironsbot.shared.features.visibility import event_has_feature

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.config.models.app import AppConfig
    from ironsbot.runtime.plugins import PluginDefinition
    from ironsbot.shared.features import FeatureService


def _any_feature_visible(
    features: FeatureService,
    event: Event,
    definition: PluginDefinition,
) -> bool:
    return any(
        event_has_feature(features, event, feature.value)
        for feature in definition.features
    )


def _messaging_visible(
    features: FeatureService,
    event: Event,
    config: AppConfig,
) -> bool:
    msg_config = config.message
    if isinstance(event, GroupMessageEvent):
        actions = [*msg_config.group_commands, *msg_config.group_schedules]
    elif isinstance(event, PrivateMessageEvent):
        actions = [*msg_config.private_commands, *msg_config.private_schedules]
    else:
        return False
    return any(
        action.enabled and event_has_feature(features, event, action.feature)
        for action in actions
    )


def _superuser_visible(features: FeatureService, event: Event) -> bool:
    user_id = getattr(event, "user_id", None)
    return user_id is not None and features.is_superuser(int(user_id))


def plugin_visible_for_event(
    definition: PluginDefinition,
    event: Event,
    *,
    features: FeatureService,
    config: AppConfig,
    ai_key_configured: bool,
) -> bool:
    help_entry = definition.help
    if help_entry is None or help_entry.visibility == "hidden":
        visible = False
    elif help_entry.visibility == "always":
        visible = True
    elif definition.id == "messaging":
        visible = _messaging_visible(features, event, config)
    elif definition.id == "team_resource":
        visible = (
            config.seer.team_resource.enabled
            and isinstance(event, GroupMessageEvent)
            and event_has_feature(
                features, event, "team_resource_subscription"
            )
        )
    elif definition.id == "ai_chat":
        visible = ai_key_configured and event_has_feature(
            features, event, "ai_chat"
        )
    elif definition.id == "ai_intent":
        visible = (
            ai_key_configured
            and config.ai.intent_actions_enabled
            and event_has_feature(features, event, "ai_intent")
        )
    elif definition.id == "headless_notice":
        visible = _superuser_visible(features, event)
    else:
        visible = _any_feature_visible(features, event, definition)
    return visible
