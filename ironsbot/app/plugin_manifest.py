# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Final

from ironsbot.plugin_catalog import (
    PLUGIN_GROUP_ORDER,
    iter_feature_module_prefixes,
    iter_plugin_modules,
    plugin_modules_for_group,
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

    @classmethod
    def missing_feature_modules(cls, modules: list[str]) -> PluginManifestError:
        return cls(
            "feature catalog references unloaded plugin modules: "
            + ", ".join(modules)
        )


def validate_plugin_manifest() -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    empty_groups: list[str] = []

    for group in PLUGIN_GROUP_ORDER:
        modules = plugin_modules_for_group(group)
        if not modules:
            empty_groups.append(group)
        for module in modules:
            if not module.strip():
                raise PluginManifestError.empty_module(group)
            if module in seen:
                duplicates.append(module)
            seen.add(module)

    if empty_groups:
        raise PluginManifestError.empty_groups(empty_groups)
    if duplicates:
        raise PluginManifestError.duplicate_modules(duplicates)

    _validate_feature_module_coverage()

    for setup_ref in RUNTIME_SETUP_CALLS:
        module_name, separator, function_name = setup_ref.partition(":")
        if (
            not separator
            or not module_name.strip()
            or not function_name.strip()
            or ":" in function_name
        ):
                raise PluginManifestError.invalid_setup_ref(setup_ref)


def _validate_feature_module_coverage() -> None:
    loaded_modules = iter_plugin_modules()
    missing_feature_modules = [
        module_prefix
        for module_prefix in iter_feature_module_prefixes()
        if not _module_prefix_is_loaded(module_prefix, loaded_modules)
    ]
    if missing_feature_modules:
        raise PluginManifestError.missing_feature_modules(missing_feature_modules)


def _module_prefix_is_loaded(
    module_prefix: str,
    loaded_modules: tuple[str, ...],
) -> bool:
    return any(
        loaded_module == module_prefix
        or loaded_module.startswith(f"{module_prefix}.")
        or module_prefix.startswith(f"{loaded_module}.")
        for loaded_module in loaded_modules
    )


__all__ = [
    "RUNTIME_SETUP_CALLS",
    "PluginManifestError",
    "iter_plugin_modules",
    "validate_plugin_manifest",
]
