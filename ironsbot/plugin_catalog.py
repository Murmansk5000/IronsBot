# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

PluginGroup = Literal["external", "core", "infrastructure", "feature"]
HelpVisibility = Literal["default", "always", "hidden"]

PLUGIN_GROUP_ORDER: Final[tuple[PluginGroup, ...]] = (
    "external",
    "core",
    "infrastructure",
    "feature",
)


@dataclass(frozen=True, slots=True)
class PluginSpec:
    module: str
    group: PluginGroup
    features: tuple[str, ...] = ()
    help_group: str | None = None
    help_order: int = 1000
    help_visibility: HelpVisibility = "default"


PLUGIN_SPECS: Final[tuple[PluginSpec, ...]] = (
    PluginSpec("nonebot_plugin_apscheduler", "external", help_visibility="hidden"),
    PluginSpec("nonebot_plugin_localstore", "external", help_visibility="hidden"),
    PluginSpec("nonebot_plugin_htmlkit", "external", help_visibility="hidden"),
    PluginSpec("nonebot_plugin_saa", "external", help_visibility="hidden"),
    PluginSpec("ironsbot.plugins.admin_priority", "core", help_visibility="hidden"),
    PluginSpec(
        "ironsbot.plugins.messaging",
        "core",
        features=(
            "text",
            "text_push",
            "web_activity_link",
            "web_activity_push",
            "seerinfo",
        ),
        help_group="message",
        help_order=30,
    ),
    PluginSpec(
        "ironsbot.plugins.db_sync",
        "infrastructure",
        help_group="admin",
        help_order=20,
        help_visibility="hidden",
    ),
    PluginSpec(
        "ironsbot.plugins.http_client",
        "infrastructure",
        help_visibility="hidden",
    ),
    PluginSpec(
        "ironsbot.plugins.seer_data",
        "infrastructure",
        help_visibility="hidden",
    ),
    PluginSpec(
        "ironsbot.plugins.headless_seer",
        "infrastructure",
        help_group="admin",
        help_order=30,
        help_visibility="hidden",
    ),
    PluginSpec(
        "ironsbot.plugins.fire_manual_ad",
        "feature",
        features=("fire_manual_ad",),
        help_visibility="hidden",
    ),
    PluginSpec(
        "ironsbot.plugins.headless_seer_notice",
        "feature",
        help_group="admin",
        help_order=40,
    ),
    PluginSpec(
        "ironsbot.plugins.red_packet_notice",
        "feature",
        help_visibility="hidden",
    ),
    PluginSpec(
        "ironsbot.plugins.ai_chat",
        "feature",
        features=("ai_chat", "admin_notice"),
        help_group="ai",
        help_order=10,
    ),
    PluginSpec(
        "ironsbot.plugins.team_resource_subscription",
        "feature",
        features=("team_resource_subscription",),
        help_group="seer",
        help_order=50,
    ),
    PluginSpec(
        "ironsbot.plugins.activity",
        "feature",
        features=("seer_activity_query", "seer_activity_push"),
        help_group="message",
        help_order=10,
    ),
    PluginSpec(
        "ironsbot.plugins.ai_mention_guard",
        "feature",
        features=("ai_chat",),
        help_visibility="hidden",
    ),
    PluginSpec(
        "ironsbot.plugins.ai_intent",
        "feature",
        features=(
            "ai_intent",
            "ai_intent_team_recommend",
            "ai_intent_fire_manual",
        ),
        help_group="ai",
        help_order=20,
    ),
    PluginSpec(
        "ironsbot.plugins.bilibili",
        "feature",
        features=("bili_query", "bili_push"),
        help_group="message",
        help_order=20,
    ),
    PluginSpec("ironsbot.plugins.bilibili.commands", "feature"),
    PluginSpec(
        "ironsbot.plugins.about",
        "feature",
        features=("about",),
        help_group="core",
        help_order=20,
        help_visibility="always",
    ),
    PluginSpec(
        "ironsbot.plugins.seer.query",
        "feature",
        features=(
            "seer",
            "seer_player",
            "seer_team",
            "seer_pet",
            "seer_mintmark",
            "seer_equipment",
            "seer_type",
            "seer_peak",
            "seer_autocard",
            "seer_rank",
            "seer_data",
        ),
        help_group="seer",
        help_order=10,
    ),
    PluginSpec("ironsbot.plugins.seer.query.commands", "feature"),
    PluginSpec(
        "ironsbot.plugins.help",
        "feature",
        features=("help",),
        help_group="core",
        help_order=10,
        help_visibility="always",
    ),
    PluginSpec(
        "ironsbot.plugins.help_hint",
        "feature",
        help_visibility="hidden",
    ),
    PluginSpec(
        "ironsbot.plugins.team_audit_welcome",
        "feature",
        features=("team_audit",),
        help_group="seer",
        help_order=60,
        help_visibility="hidden",
    ),
    PluginSpec(
        "ironsbot.plugins.sendpic",
        "feature",
        features=("image",),
        help_group="seer",
        help_order=30,
        help_visibility="hidden",
    ),
    PluginSpec(
        "ironsbot.plugins.meeting",
        "feature",
        features=("meeting",),
        help_group="message",
        help_order=40,
    ),
    PluginSpec(
        "ironsbot.plugins.seer.rank_help",
        "feature",
        features=("seer_rank",),
        help_group="seer",
        help_order=20,
    ),
    PluginSpec(
        "ironsbot.plugins.scheduled_restart",
        "feature",
        help_visibility="hidden",
    ),
    PluginSpec(
        "ironsbot.plugins.server_status",
        "feature",
        features=("server_status_query", "server_status_push"),
        help_group="seer",
        help_order=70,
    ),
    PluginSpec("ironsbot.plugins.server_status.handlers", "feature"),
    PluginSpec(
        "ironsbot.plugins.startup_notice",
        "feature",
        help_visibility="hidden",
    ),
)


def plugin_modules_for_group(group: PluginGroup) -> tuple[str, ...]:
    return tuple(spec.module for spec in PLUGIN_SPECS if spec.group == group)


def iter_plugin_modules() -> tuple[str, ...]:
    return tuple(
        module
        for group in PLUGIN_GROUP_ORDER
        for module in plugin_modules_for_group(group)
    )


def features_for_plugin_module(module_name: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            feature
            for spec in PLUGIN_SPECS
            if module_name == spec.module
            or module_name.startswith(f"{spec.module}.")
            for feature in spec.features
        )
    )


def iter_feature_module_prefixes() -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            spec.module
            for spec in PLUGIN_SPECS
            if spec.features
        )
    )


def _matching_specs(module_name: str) -> tuple[PluginSpec, ...]:
    return tuple(
        sorted(
            (
                spec
                for spec in PLUGIN_SPECS
                if module_name == spec.module
                or module_name.startswith(f"{spec.module}.")
            ),
            key=lambda spec: len(spec.module),
            reverse=True,
        )
    )


def help_layout_for_module(module_name: str) -> tuple[str, int]:
    for spec in _matching_specs(module_name):
        if spec.help_group is not None:
            return spec.help_group, spec.help_order
    return "other", 1000


def help_visibility_for_module(module_name: str) -> HelpVisibility:
    matches = _matching_specs(module_name)
    return matches[0].help_visibility if matches else "hidden"


__all__ = [
    "PLUGIN_GROUP_ORDER",
    "PLUGIN_SPECS",
    "HelpVisibility",
    "PluginGroup",
    "PluginSpec",
    "features_for_plugin_module",
    "help_layout_for_module",
    "help_visibility_for_module",
    "iter_feature_module_prefixes",
    "iter_plugin_modules",
    "plugin_modules_for_group",
]
