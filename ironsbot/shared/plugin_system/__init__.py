# SPDX-License-Identifier: MIT
from __future__ import annotations

from .adapters import dispatch_plugin
from .base import Plugin, PluginContext
from .registry import (
    PluginRegistry,
    PluginRegistryError,
    plugin_registry,
    register_plugin,
)

__all__ = [
    "Plugin",
    "PluginContext",
    "PluginRegistry",
    "PluginRegistryError",
    "dispatch_plugin",
    "plugin_registry",
    "register_plugin",
]
