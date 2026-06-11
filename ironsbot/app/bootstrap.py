# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from ironsbot.app.plugin_manifest import (
    iter_plugin_modules,
    validate_plugin_manifest,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class BootstrapState:
    driver: Any
    app: Any
    loaded_plugins: tuple[str, ...]


def load_manifest_plugins(
    load_plugin: Callable[[str], object] | None = None,
) -> tuple[str, ...]:
    validate_plugin_manifest()
    modules = iter_plugin_modules()
    plugin_loader = load_plugin or nonebot.load_plugin

    for module in modules:
        plugin_loader(module)

    return modules


def bootstrap() -> BootstrapState:
    nonebot.init()

    driver = nonebot.get_driver()
    driver.register_adapter(ONEBOT_V11Adapter)

    app = nonebot.get_asgi()
    loaded_plugins = load_manifest_plugins()
    return BootstrapState(driver=driver, app=app, loaded_plugins=loaded_plugins)


__all__ = [
    "BootstrapState",
    "bootstrap",
    "load_manifest_plugins",
]
