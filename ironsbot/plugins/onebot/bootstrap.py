# SPDX-License-Identifier: MIT
"""Temporary standard-NoneBot entrypoint for existing IronsBot contributions.

The TOML manifest discovers this module through NoneBot itself. The central
registry remains only as a migration bridge while individual contribution
modules move out of it; it must not become a second discovery system.
"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from ironsbot.app.registry import build_plugin_registry
from ironsbot.runtime.plugins import current_plugin_install_context

__plugin_meta__ = PluginMetadata(
    name="IronsBot OneBot runtime",
    description="Install IronsBot OneBot v11 contributions from the selected profile.",
    usage="Configured by IronsBot's bundled NoneBot TOML manifest.",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

_context = current_plugin_install_context()
_context.contribute(
    __plugin_meta__,
    *build_plugin_registry(
        settings=_context.settings,
        resources=_context.resources,
        scheduler=_context.scheduler,
    ),
)
