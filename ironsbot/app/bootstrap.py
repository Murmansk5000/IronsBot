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
    build_headless_service,
)
from ironsbot.app.file_logging import configure_file_logging
from ironsbot.app.registry import build_plugin_registry
from ironsbot.config.loader import (
    get_app_config,
    load_credentials_config,
    load_secrets_config,
)
from ironsbot.runtime.matchers import MatcherRegistry
from ironsbot.shared.features import FeatureService
from ironsbot.shared.messaging.admin_notice import AdminNoticeService
from ironsbot.shared.messaging.bot_router import BotRouter
from ironsbot.shared.messaging.command_cooldown import CommandCooldownService
from ironsbot.shared.messaging.outbound_rate_limit import (
    GroupOutboundRateLimitService,
    install_outbound_rate_limit_hooks,
)
from ironsbot.shared.messaging.senders import DeliveryResources

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

    from ironsbot.app.lifecycle import ApplicationLifecycle
    from ironsbot.runtime.plugins import PluginDefinition
    from ironsbot.services.operations.headless import HeadlessService


@dataclass(frozen=True, slots=True)
class BootstrapState:
    driver: Driver
    app: Any
    plugins: tuple[PluginDefinition, ...]
    matchers: MatcherRegistry
    lifecycle: ApplicationLifecycle
    activity: ActivityComponent
    headless: HeadlessService


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
    features = FeatureService(
        config.feature,
        frozenset(int(value) for value in driver.config.superusers),
    )
    outbound = GroupOutboundRateLimitService(
        config.message.outbound_rate_limit,
        features,
    )
    delivery = DeliveryResources(
        outbound,
        config.message.push_unsubscribe,
        BotRouter(
            config.runtime.bot_routing,
            config.feature.group_aliases,
            config.feature.user_aliases,
        ),
    )
    admin_notices = AdminNoticeService(features, delivery)
    install_outbound_rate_limit_hooks(outbound)

    app = nonebot.get_asgi()
    activity = build_activity_component(
        config.activity,
        features,
        delivery,
        push_subscription_path=config.message.push_unsubscribe.data_path,
    )
    secrets = load_secrets_config()
    headless = build_headless_service(
        config.runtime,
        load_credentials_config(),
        admin_notices,
    )
    plugins = build_plugin_registry(
        config=config,
        features=features,
        delivery=delivery,
        admin_notices=admin_notices,
        activity_service=activity.service,
        headless=headless,
        secrets=secrets,
        shutdown_activity=activity.close,
    )
    matchers = MatcherRegistry(
        CommandCooldownService(config.runtime.command_cooldown, features),
        config.runtime.matcher_priority,
    )
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
        headless=headless,
    )
