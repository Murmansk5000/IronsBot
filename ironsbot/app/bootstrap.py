# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter

from ironsbot.app.composition import (
    ActivityComponent,
    build_activity_component,
    build_application_lifecycle,
)
from ironsbot.app.file_logging import configure_file_logging
from ironsbot.app.registry import build_plugin_registry
from ironsbot.config.loader import get_app_config
from ironsbot.runtime.matchers import MatcherRegistry

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

    from ironsbot.app.lifecycle import ApplicationLifecycle
    from ironsbot.runtime.plugins import PluginDefinition


@dataclass(frozen=True, slots=True)
class BootstrapState:
    driver: Driver
    app: Any
    plugins: tuple[PluginDefinition, ...]
    matchers: MatcherRegistry
    lifecycle: ApplicationLifecycle
    activity: ActivityComponent


def configure_third_party_logging() -> None:
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def bootstrap() -> BootstrapState:
    configure_third_party_logging()
    config = get_app_config()
    nonebot.init()
    configure_file_logging(config.runtime.logging)

    driver = nonebot.get_driver()
    driver.register_adapter(ONEBOT_V11Adapter)

    app = nonebot.get_asgi()
    activity = build_activity_component(
        config.activity,
        push_subscription_path=config.message.push_unsubscribe.data_path,
    )
    plugins = build_plugin_registry(
        activity_service=activity.service,
        restart_config=config.runtime.restart,
        shutdown_activity=activity.close,
        startup_config=config.runtime.startup_notice,
    )
    matchers = MatcherRegistry()
    for plugin in plugins:
        plugin.install(matchers)
    matchers.install_postprocessor()

    lifecycle = build_application_lifecycle(driver, plugins)
    lifecycle.install()
    return BootstrapState(
        driver=driver,
        app=app,
        plugins=plugins,
        matchers=matchers,
        lifecycle=lifecycle,
        activity=activity,
    )


__all__ = [
    "BootstrapState",
    "bootstrap",
]
