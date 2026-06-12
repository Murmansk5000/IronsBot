# SPDX-License-Identifier: MIT
from __future__ import annotations

FeatureModuleRegistry = dict[str, tuple[str, ...]]


FEATURE_REGISTRY: FeatureModuleRegistry = {
    "about": ("ironsbot.plugins.about",),
    "help": ("ironsbot.plugins.help",),
    "seer": (
        "ironsbot.custom_plugins.custom_get_seer_info",
        "ironsbot.custom_plugins.pet_config_reply",
    ),
    "image": ("ironsbot.plugins.sendpic",),
    "rank": ("ironsbot.custom_plugins.rank_help",),
    "meeting": ("ironsbot.plugins.meeting",),
    "text": ("ironsbot.custom_plugins.message_actions",),
    "text_push": ("ironsbot.custom_plugins.message_actions",),
    "activity_link": ("ironsbot.custom_plugins.message_actions",),
    "activity_link_push": ("ironsbot.custom_plugins.message_actions",),
    "seerinfo": ("ironsbot.custom_plugins.message_actions",),
    "bili_query": ("ironsbot.plugins.bilibili",),
    "bili_push": ("ironsbot.plugins.bilibili",),
    "activity_query": ("ironsbot.plugins.activity",),
    "activity_push": ("ironsbot.plugins.activity",),
    "server_status_query": ("ironsbot.plugins.server_status",),
    "server_status_push": ("ironsbot.plugins.server_status",),
    "team": ("ironsbot.custom_plugins.team_shortcut",),
    "ai_chat": ("ironsbot.plugins.ai_chat",),
    "ai_intent": ("ironsbot.plugins.ai_intent",),
    "admin_notice": ("ironsbot.plugins.ai_chat",),
}


def module_for_feature(feature: str) -> tuple[str, ...]:
    """Return configured plugin module prefixes for a feature."""
    return FEATURE_REGISTRY.get(feature, ())


def features_for_module(module_name: str) -> tuple[str, ...]:
    """Infer feature keys from a plugin module prefix."""
    features: list[str] = []
    for feature, modules in FEATURE_REGISTRY.items():
        if any(module_name.startswith(module_prefix) for module_prefix in modules):
            features.append(feature)
    return tuple(features)


__all__ = [
    "FEATURE_REGISTRY",
    "FeatureModuleRegistry",
    "features_for_module",
    "module_for_feature",
]
