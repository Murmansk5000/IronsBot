# SPDX-License-Identifier: MIT
"""Temporary standard-NoneBot entrypoint for configured private extensions.

The TOML manifest discovers this module through NoneBot itself. Built-in
contributions are declared by their own manifest-loaded packages; this adapter
must not become a second discovery system.
"""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

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
    *_context.resources.private_extensions.load_plugin_contributions(
        _context.resources.private_extension_runtime,
    ),
)
