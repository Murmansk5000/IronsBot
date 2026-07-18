# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from ironsbot.app.file_logging import configure_file_logging
from ironsbot.app.plugin_manifest import (
    iter_plugin_modules,
    runtime_setup_callbacks,
    validate_plugin_manifest,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class BootstrapState:
    driver: Any
    app: Any
    loaded_plugins: tuple[str, ...]
    runtime_setups: tuple[str, ...]


def configure_third_party_logging() -> None:
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def load_manifest_plugins(
    load_plugin: Callable[[str], object] | None = None,
) -> tuple[str, ...]:
    validate_plugin_manifest()
    modules = iter_plugin_modules()
    plugin_loader = load_plugin or nonebot.load_plugin

    for module in modules:
        plugin_loader(module)

    return modules


def run_runtime_setups(
    setups: tuple[Callable[[], object], ...] | None = None,
) -> tuple[str, ...]:
    validate_plugin_manifest()
    callbacks = runtime_setup_callbacks() if setups is None else setups

    for setup in callbacks:
        setup()

    return tuple(f"{setup.__module__}.{setup.__qualname__}" for setup in callbacks)


def bootstrap() -> BootstrapState:
    configure_third_party_logging()
    nonebot.init()
    configure_file_logging()

    driver = nonebot.get_driver()
    driver.register_adapter(ONEBOT_V11Adapter)

    app = nonebot.get_asgi()
    loaded_plugins = load_manifest_plugins()
    runtime_setups = run_runtime_setups()
    return BootstrapState(
        driver=driver,
        app=app,
        loaded_plugins=loaded_plugins,
        runtime_setups=runtime_setups,
    )


__all__ = [
    "BootstrapState",
    "bootstrap",
    "load_manifest_plugins",
    "run_runtime_setups",
]
