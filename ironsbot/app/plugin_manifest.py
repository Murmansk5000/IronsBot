# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.plugin_catalog import (
    PLUGIN_GROUP_ORDER,
    iter_feature_module_prefixes,
    iter_plugin_modules,
    plugin_modules_for_group,
)

if TYPE_CHECKING:
    from collections.abc import Callable


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


def runtime_setup_callbacks() -> tuple[Callable[[], object], ...]:
    from ironsbot.app.command_cooldown_manifest import (
        setup_command_cooldown_manifest_runtime,
    )
    from ironsbot.plugins.activity.runtime import setup_activity_reminder_runtime
    from ironsbot.plugins.bilibili.runtime import setup_bilibili_monitor_runtime
    from ironsbot.plugins.db_sync.runtime import setup_db_sync_runtime
    from ironsbot.plugins.headless_seer.runtime import setup_headless_seer_runtime
    from ironsbot.plugins.headless_seer_notice.runtime import (
        setup_headless_notice_runtime,
    )
    from ironsbot.plugins.http_client.runtime import setup_http_client_runtime
    from ironsbot.plugins.messaging.runtime import setup_messaging_runtime
    from ironsbot.plugins.scheduled_restart.runtime import (
        setup_scheduled_restart_runtime,
    )
    from ironsbot.plugins.seer.query.runtime import (
        setup_local_rank_scheduler_runtime,
        setup_render_crash_report_runtime,
    )
    from ironsbot.plugins.server_status.runtime import setup_docker_update_runtime
    from ironsbot.plugins.startup_notice.runtime import setup_startup_notice_runtime
    from ironsbot.plugins.team_audit_welcome.runtime import (
        setup_team_audit_welcome_runtime,
    )
    from ironsbot.plugins.team_resource_subscription.runtime import (
        setup_team_resource_runtime,
    )
    from ironsbot.shared.messaging.outbound_rate_limit import (
        setup_outbound_rate_limit_runtime,
    )
    from ironsbot.shared.plugin_runtime.startup_ready_runtime import (
        setup_startup_ready_runtime,
    )

    return (
        setup_command_cooldown_manifest_runtime,
        setup_outbound_rate_limit_runtime,
        setup_docker_update_runtime,
        setup_db_sync_runtime,
        setup_http_client_runtime,
        setup_headless_seer_runtime,
        setup_messaging_runtime,
        setup_headless_notice_runtime,
        setup_scheduled_restart_runtime,
        setup_startup_ready_runtime,
        setup_startup_notice_runtime,
        setup_bilibili_monitor_runtime,
        setup_activity_reminder_runtime,
        setup_team_resource_runtime,
        setup_local_rank_scheduler_runtime,
        setup_team_audit_welcome_runtime,
        setup_render_crash_report_runtime,
    )


__all__ = [
    "PluginManifestError",
    "iter_plugin_modules",
    "runtime_setup_callbacks",
    "validate_plugin_manifest",
]
