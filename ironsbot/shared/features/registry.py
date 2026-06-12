# SPDX-License-Identifier: MIT
from __future__ import annotations

FeatureModuleRegistry = dict[str, tuple[str, ...]]


FEATURE_REGISTRY: FeatureModuleRegistry = {
    "about": ("ironsbot.plugins.about",),
    "help": ("ironsbot.plugins.help",),
    "seer": (
        "ironsbot.plugins.seer.query",
        "ironsbot.plugins.seer.pet_config_reply",
    ),
    "image": ("ironsbot.plugins.sendpic",),
    "rank": ("ironsbot.plugins.seer.rank_help",),
    "meeting": ("ironsbot.plugins.meeting",),
    "text": ("ironsbot.plugins.messaging",),
    "text_push": ("ironsbot.plugins.messaging",),
    "activity_link": ("ironsbot.plugins.messaging",),
    "activity_link_push": ("ironsbot.plugins.messaging",),
    "seerinfo": ("ironsbot.plugins.messaging",),
    "bili_query": ("ironsbot.plugins.bilibili",),
    "bili_push": ("ironsbot.plugins.bilibili",),
    "activity_query": ("ironsbot.plugins.activity",),
    "activity_push": ("ironsbot.plugins.activity",),
    "server_status_query": ("ironsbot.plugins.server_status",),
    "server_status_push": ("ironsbot.plugins.server_status",),
    "team": ("ironsbot.plugins.team_shortcut",),
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
