# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

import nonebot

if TYPE_CHECKING:
    from ironsbot.runtime.matchers import MatcherRegistry
    from ironsbot.runtime.plugins import PluginInstall


class ExternalPluginLoadError(ValueError):
    def __init__(self, module: str) -> None:
        super().__init__(f"failed to load external plugin: {module}")


def load_external_plugin(module: str) -> None:
    if nonebot.load_plugin(module) is None:
        raise ExternalPluginLoadError(module)


def external_install(module: str) -> PluginInstall:
    def install(_registry: MatcherRegistry) -> None:
        load_external_plugin(module)

    return install
