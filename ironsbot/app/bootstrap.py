# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from ironsbot.app.composition import build_application_lifecycle
from ironsbot.app.file_logging import configure_file_logging
from ironsbot.app.plugin_manifest import (
    iter_plugin_modules,
    validate_plugin_manifest,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot.internal.driver import Driver

    from ironsbot.app.lifecycle import ApplicationLifecycle


@dataclass(frozen=True, slots=True)
class BootstrapState:
    driver: Driver
    app: Any
    loaded_plugins: tuple[str, ...]
    lifecycle: ApplicationLifecycle


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


def bootstrap() -> BootstrapState:
    configure_third_party_logging()
    nonebot.init()
    configure_file_logging()

    driver = nonebot.get_driver()
    driver.register_adapter(ONEBOT_V11Adapter)

    app = nonebot.get_asgi()
    loaded_plugins = load_manifest_plugins()
    from nonebot_plugin_apscheduler import scheduler

    lifecycle = build_application_lifecycle(driver, scheduler)
    lifecycle.install()
    return BootstrapState(
        driver=driver,
        app=app,
        loaded_plugins=loaded_plugins,
        lifecycle=lifecycle,
    )


__all__ = [
    "BootstrapState",
    "bootstrap",
    "load_manifest_plugins",
]
