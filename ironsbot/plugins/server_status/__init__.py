# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.shared.plugin_system import register_plugin

from .metadata import __plugin_meta__ as __plugin_meta__
from .plugin import ServerStatusPlugin

register_plugin(ServerStatusPlugin())
