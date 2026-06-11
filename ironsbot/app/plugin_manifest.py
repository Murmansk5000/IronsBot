# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class PluginGroup:
    name: str
    modules: tuple[str, ...]


EXTERNAL_PLUGINS: Final[tuple[str, ...]] = (
    "nonebot_plugin_apscheduler",
    "nonebot_plugin_localstore",
    "nonebot_plugin_htmlkit",
    "nonebot_plugin_saa",
)

CUSTOM_CORE_PLUGINS: Final[tuple[str, ...]] = (
    "ironsbot.custom_plugins.superuser_priority",
    "ironsbot.custom_plugins.message_actions",
)

INFRASTRUCTURE_PLUGINS: Final[tuple[str, ...]] = (
    "ironsbot.plugins.db_sync",
    "ironsbot.plugins.http_client",
    "ironsbot.plugins.seer_data",
    "ironsbot.plugins.headless_seer",
)

CUSTOM_PLUGINS: Final[tuple[str, ...]] = (
    "ironsbot.custom_plugins.headless_seer_notice",
    "ironsbot.custom_plugins.ai_chat",
    "ironsbot.custom_plugins.team_shortcut",
    "ironsbot.custom_plugins.activity_reminder",
    "ironsbot.custom_plugins.ai_mention_guard",
    "ironsbot.custom_plugins.ai_intent_actions",
    "ironsbot.custom_plugins.bilibili_monitor",
    "ironsbot.custom_plugins.custom_about",
    "ironsbot.custom_plugins.custom_get_seer_info",
    "ironsbot.custom_plugins.custom_help",
    "ironsbot.custom_plugins.custom_sendpic",
    "ironsbot.custom_plugins.meeting_reply",
    "ironsbot.custom_plugins.pet_config_reply",
    "ironsbot.custom_plugins.rank_help",
    "ironsbot.custom_plugins.scheduled_restart",
    "ironsbot.custom_plugins.server_status",
    "ironsbot.custom_plugins.startup_notice",
)

RUNTIME_SETUP_CALLS: Final[tuple[str, ...]] = (
    "ironsbot.custom_plugins.message_actions.reply_limits:setup_reply_line_limit_api_hook",
    "ironsbot.custom_plugins.message_actions.runtime:setup_message_actions_runtime",
    "ironsbot.custom_plugins.headless_seer_notice:setup_headless_notice_runtime",
    "ironsbot.custom_plugins.scheduled_restart:setup_scheduled_restart_runtime",
    "ironsbot.custom_plugins.startup_ready:setup_startup_ready_runtime",
    "ironsbot.custom_plugins.startup_notice:setup_startup_notice_runtime",
    "ironsbot.custom_plugins.bilibili_monitor.service:setup_bilibili_monitor_runtime",
)

PLUGIN_GROUPS: Final[tuple[PluginGroup, ...]] = (
    PluginGroup("external", EXTERNAL_PLUGINS),
    PluginGroup("custom_core", CUSTOM_CORE_PLUGINS),
    PluginGroup("infrastructure", INFRASTRUCTURE_PLUGINS),
    PluginGroup("custom", CUSTOM_PLUGINS),
)


class PluginManifestError(ValueError):
    """Raised when the static plugin manifest is internally inconsistent."""

    @classmethod
    def empty_module(cls, group_name: str) -> PluginManifestError:
        return cls(f"plugin group {group_name} contains an empty module name")

    @classmethod
    def empty_groups(cls, group_names: list[str]) -> PluginManifestError:
        return cls(
            f"plugin manifest groups must not be empty: {', '.join(group_names)}"
        )

    @classmethod
    def duplicate_modules(cls, modules: list[str]) -> PluginManifestError:
        return cls(f"plugin manifest contains duplicate modules: {', '.join(modules)}")

    @classmethod
    def invalid_setup_ref(cls, setup_ref: str) -> PluginManifestError:
        return cls(f"runtime setup reference must use module:function: {setup_ref}")


def iter_plugin_modules() -> tuple[str, ...]:
    return tuple(
        module
        for group in PLUGIN_GROUPS
        for module in group.modules
    )


def validate_plugin_manifest() -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    empty_groups: list[str] = []

    for group in PLUGIN_GROUPS:
        if not group.modules:
            empty_groups.append(group.name)
        for module in group.modules:
            if not module.strip():
                raise PluginManifestError.empty_module(group.name)
            if module in seen:
                duplicates.append(module)
            seen.add(module)

    if empty_groups:
        raise PluginManifestError.empty_groups(empty_groups)
    if duplicates:
        raise PluginManifestError.duplicate_modules(duplicates)

    for setup_ref in RUNTIME_SETUP_CALLS:
        module_name, separator, function_name = setup_ref.partition(":")
        if (
            not separator
            or not module_name.strip()
            or not function_name.strip()
            or ":" in function_name
        ):
            raise PluginManifestError.invalid_setup_ref(setup_ref)


__all__ = [
    "CUSTOM_CORE_PLUGINS",
    "CUSTOM_PLUGINS",
    "EXTERNAL_PLUGINS",
    "INFRASTRUCTURE_PLUGINS",
    "PLUGIN_GROUPS",
    "RUNTIME_SETUP_CALLS",
    "PluginGroup",
    "PluginManifestError",
    "iter_plugin_modules",
    "validate_plugin_manifest",
]
