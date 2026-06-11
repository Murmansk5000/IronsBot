# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from .base import Plugin, PluginContext


PLUGIN_NAME_REQUIRED = "plugin name must not be empty"
DISPATCH_TARGET_REQUIRED = "plugin_name or feature is required"


def _plugin_feature_required_message(plugin_name: str) -> str:
    return f"plugin {plugin_name} feature must not be empty"


def _plugin_not_registered_message(plugin_name: str) -> str:
    return f"plugin not registered: {plugin_name}"


def _plugin_disabled_message(plugin_name: str) -> str:
    return f"plugin disabled: {plugin_name}"


def _feature_not_enabled_message(feature: str) -> str:
    return f"no enabled plugin for feature: {feature}"


class PluginRegistryError(RuntimeError):
    """Raised when plugin dispatch cannot resolve a valid handler."""


@dataclass(slots=True)
class PluginRegistry:
    _plugins: dict[str, Plugin] = field(default_factory=dict)
    _feature_index: dict[str, list[str]] = field(default_factory=dict)
    _disabled_plugins: set[str] = field(default_factory=set)

    def register(self, plugin: Plugin) -> Plugin:
        name = plugin.name.strip()
        feature = plugin.feature.strip()
        if not name:
            raise PluginRegistryError(PLUGIN_NAME_REQUIRED)
        if not feature:
            raise PluginRegistryError(_plugin_feature_required_message(name))

        old_plugin = self._plugins.get(name)
        if old_plugin is not None:
            old_feature_plugins = self._feature_index.get(old_plugin.feature, [])
            self._feature_index[old_plugin.feature] = [
                plugin_name
                for plugin_name in old_feature_plugins
                if plugin_name != name
            ]

        self._plugins[name] = plugin
        self._feature_index.setdefault(feature, [])
        if name not in self._feature_index[feature]:
            self._feature_index[feature].append(name)
        if getattr(plugin, "enabled", True):
            self._disabled_plugins.discard(name)
        else:
            self._disabled_plugins.add(name)
        return plugin

    def enable(self, plugin_name: str) -> None:
        self._require_plugin(plugin_name)
        self._disabled_plugins.discard(plugin_name)

    def disable(self, plugin_name: str) -> None:
        self._require_plugin(plugin_name)
        self._disabled_plugins.add(plugin_name)

    def resolve_handler(
        self,
        *,
        plugin_name: str | None = None,
        feature: str | None = None,
    ) -> Plugin:
        if plugin_name:
            plugin = self._plugins.get(plugin_name)
            if plugin is None:
                raise PluginRegistryError(_plugin_not_registered_message(plugin_name))
            if self._is_disabled(plugin):
                raise PluginRegistryError(_plugin_disabled_message(plugin_name))
            return plugin

        if feature:
            for candidate_name in self._feature_index.get(feature, []):
                candidate = self._plugins[candidate_name]
                if not self._is_disabled(candidate):
                    return candidate
            raise PluginRegistryError(_feature_not_enabled_message(feature))

        raise PluginRegistryError(DISPATCH_TARGET_REQUIRED)

    async def dispatch(
        self,
        event: Event,
        context: PluginContext,
        *,
        plugin_name: str | None = None,
        feature: str | None = None,
    ) -> Any:
        plugin = self.resolve_handler(plugin_name=plugin_name, feature=feature)
        return await plugin.handle(event, context)

    def registered_plugins(self) -> tuple[str, ...]:
        return tuple(self._plugins)

    def plugins_for_feature(self, feature: str) -> tuple[str, ...]:
        return tuple(self._feature_index.get(feature, ()))

    def _require_plugin(self, plugin_name: str) -> None:
        if plugin_name not in self._plugins:
            raise PluginRegistryError(_plugin_not_registered_message(plugin_name))

    def _is_disabled(self, plugin: Plugin) -> bool:
        return plugin.name in self._disabled_plugins or not getattr(
            plugin,
            "enabled",
            True,
        )


plugin_registry = PluginRegistry()


def register_plugin(plugin: Plugin) -> Plugin:
    return plugin_registry.register(plugin)
