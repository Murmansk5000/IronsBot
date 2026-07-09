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

CORE_PLUGINS: Final[tuple[str, ...]] = (
    "ironsbot.plugins.admin_priority",
    "ironsbot.plugins.messaging",
)

INFRASTRUCTURE_PLUGINS: Final[tuple[str, ...]] = (
    "ironsbot.plugins.db_sync",
    "ironsbot.plugins.http_client",
    "ironsbot.plugins.seer_data",
    "ironsbot.plugins.headless_seer",
)

FEATURE_PLUGINS: Final[tuple[str, ...]] = (
    "ironsbot.plugins.fire_manual_ad",
    "ironsbot.plugins.headless_seer_notice",
    "ironsbot.plugins.red_packet_notice",
    "ironsbot.plugins.ai_chat",
    "ironsbot.plugins.team_resource_subscription",
    "ironsbot.plugins.activity",
    "ironsbot.plugins.ai_mention_guard",
    "ironsbot.plugins.ai_intent",
    "ironsbot.plugins.team_recommend",
    "ironsbot.plugins.bilibili",
    "ironsbot.plugins.bilibili.commands",
    "ironsbot.plugins.about",
    "ironsbot.plugins.seer.query",
    "ironsbot.plugins.seer.query.commands",
    "ironsbot.plugins.help",
    "ironsbot.plugins.help_hint",
    "ironsbot.plugins.team_audit_welcome",
    "ironsbot.plugins.sendpic",
    "ironsbot.plugins.meeting",
    "ironsbot.plugins.seer.rank_help",
    "ironsbot.plugins.scheduled_restart",
    "ironsbot.plugins.server_status",
    "ironsbot.plugins.server_status.handlers",
    "ironsbot.plugins.startup_notice",
)

RUNTIME_SETUP_CALLS: Final[tuple[str, ...]] = (
    "ironsbot.plugins.server_status.runtime:setup_docker_update_runtime",
    "ironsbot.plugins.db_sync.runtime:setup_db_sync_runtime",
    "ironsbot.plugins.http_client.runtime:setup_http_client_runtime",
    "ironsbot.plugins.headless_seer.runtime:setup_headless_seer_runtime",
    "ironsbot.plugins.messaging.runtime:setup_messaging_runtime",
    "ironsbot.plugins.headless_seer_notice.runtime:setup_headless_notice_runtime",
    "ironsbot.plugins.scheduled_restart.runtime:setup_scheduled_restart_runtime",
    "ironsbot.shared.plugin_runtime.startup_ready_runtime:setup_startup_ready_runtime",
    "ironsbot.plugins.startup_notice.runtime:setup_startup_notice_runtime",
    "ironsbot.plugins.bilibili.runtime:setup_bilibili_monitor_runtime",
    "ironsbot.plugins.activity.runtime:setup_activity_reminder_runtime",
    "ironsbot.plugins.team_resource_subscription.runtime:setup_team_resource_runtime",
    "ironsbot.plugins.seer.query.runtime:setup_local_rank_scheduler_runtime",
    "ironsbot.plugins.team_audit_welcome.runtime:setup_team_audit_welcome_runtime",
    "ironsbot.plugins.seer.query.runtime:setup_render_crash_report_runtime",
)

PLUGIN_GROUPS: Final[tuple[PluginGroup, ...]] = (
    PluginGroup("external", EXTERNAL_PLUGINS),
    PluginGroup("core", CORE_PLUGINS),
    PluginGroup("infrastructure", INFRASTRUCTURE_PLUGINS),
    PluginGroup("feature", FEATURE_PLUGINS),
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
    "CORE_PLUGINS",
    "EXTERNAL_PLUGINS",
    "FEATURE_PLUGINS",
    "INFRASTRUCTURE_PLUGINS",
    "PLUGIN_GROUPS",
    "RUNTIME_SETUP_CALLS",
    "PluginGroup",
    "PluginManifestError",
    "iter_plugin_modules",
    "validate_plugin_manifest",
]
