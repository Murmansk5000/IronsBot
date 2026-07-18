# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.core.features import FEATURE_KEYS
from ironsbot.plugin_catalog import (
    PLUGIN_GROUP_ORDER,
    PLUGIN_SPECS,
    iter_feature_module_prefixes,
    iter_plugin_modules,
    plugin_modules_for_group,
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
    def missing_feature_modules(cls, modules: list[str]) -> PluginManifestError:
        return cls(
            "feature catalog references unloaded plugin modules: "
            + ", ".join(modules)
        )

    @classmethod
    def unknown_features(cls, features: list[str]) -> PluginManifestError:
        return cls(
            "plugin catalog references unknown features: " + ", ".join(features)
        )

    @classmethod
    def unowned_features(cls, features: list[str]) -> PluginManifestError:
        return cls("features have no owning plugin: " + ", ".join(features))


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

    owned_features = {
        feature for plugin in PLUGIN_SPECS for feature in plugin.features
    }
    unknown_features = sorted(owned_features - FEATURE_KEYS)
    if unknown_features:
        raise PluginManifestError.unknown_features(unknown_features)
    unowned_features = sorted(FEATURE_KEYS - owned_features)
    if unowned_features:
        raise PluginManifestError.unowned_features(unowned_features)

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


__all__ = [
    "PluginManifestError",
    "iter_plugin_modules",
    "validate_plugin_manifest",
]
