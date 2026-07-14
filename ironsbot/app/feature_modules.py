# SPDX-License-Identifier: MIT
from __future__ import annotations

FeatureModuleRegistry = dict[str, tuple[str, ...]]

FEATURE_MODULE_REGISTRY: FeatureModuleRegistry = {
    "about": ("ironsbot.plugins.about",),
    "help": ("ironsbot.plugins.help",),
    "seer": ("ironsbot.plugins.seer.query",),
    "seer_player": ("ironsbot.plugins.seer.query",),
    "seer_team": ("ironsbot.plugins.seer.query",),
    "seer_pet": ("ironsbot.plugins.seer.query",),
    "seer_mintmark": ("ironsbot.plugins.seer.query",),
    "seer_equipment": ("ironsbot.plugins.seer.query",),
    "seer_type": ("ironsbot.plugins.seer.query",),
    "seer_peak": ("ironsbot.plugins.seer.query",),
    "seer_autocard": ("ironsbot.plugins.seer.query",),
    "seer_rank": (
        "ironsbot.plugins.seer.query",
        "ironsbot.plugins.seer.rank_help",
    ),
    "seer_data": ("ironsbot.plugins.seer.query",),
    "image": ("ironsbot.plugins.sendpic",),
    "meeting": ("ironsbot.plugins.meeting",),
    "text": ("ironsbot.plugins.messaging",),
    "text_push": ("ironsbot.plugins.messaging",),
    "web_activity_link": ("ironsbot.plugins.messaging",),
    "web_activity_push": ("ironsbot.plugins.messaging",),
    "seerinfo": ("ironsbot.plugins.messaging",),
    "bili_query": ("ironsbot.plugins.bilibili",),
    "bili_push": ("ironsbot.plugins.bilibili",),
    "seer_activity_query": ("ironsbot.plugins.activity",),
    "seer_activity_push": ("ironsbot.plugins.activity",),
    "server_status_query": ("ironsbot.plugins.server_status",),
    "server_status_push": ("ironsbot.plugins.server_status",),
    "team_resource_subscription": ("ironsbot.plugins.team_resource_subscription",),
    "team_audit": ("ironsbot.plugins.team_audit_welcome",),
    "ai_chat": ("ironsbot.plugins.ai_chat",),
    "ai_intent": (
        "ironsbot.plugins.ai_intent",
        "ironsbot.plugins.team_recommend",
    ),
    "fire_manual_ad": ("ironsbot.plugins.fire_manual_ad",),
    "admin_notice": ("ironsbot.plugins.ai_chat",),
}


def features_for_plugin_module(module_name: str) -> tuple[str, ...]:
    features: list[str] = []
    for feature, modules in FEATURE_MODULE_REGISTRY.items():
        if any(module_name.startswith(module_prefix) for module_prefix in modules):
            features.append(feature)
    return tuple(features)


def iter_feature_module_prefixes() -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            module_prefix
            for modules in FEATURE_MODULE_REGISTRY.values()
            for module_prefix in modules
        )
    )


__all__ = [
    "FEATURE_MODULE_REGISTRY",
    "FeatureModuleRegistry",
    "features_for_plugin_module",
    "iter_feature_module_prefixes",
]
