# SPDX-License-Identifier: MIT
"""Configured application runtime assembled by the composition root."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.core.platform import Platform
from ironsbot.integrations.nonebot_host import NoneBotHostBinding

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

    from ironsbot.app.file_logging import FileLogging
    from ironsbot.app.resources import ApplicationResources
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.features import Feature
    from ironsbot.core.plugin_install import PluginContribution
    from ironsbot.extensions.registration import ExtensionServices
    from ironsbot.integrations.db_registry import DatabaseManager
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.integrations.onebot.transport import OneBotTransport
    from ironsbot.integrations.scheduler.facade import SchedulerFacade
    from ironsbot.services.portable_commands import PortableCommandRouter


@dataclass(slots=True)
class Application:
    """Own process resources and explicitly composed business contributions."""

    settings: Settings
    driver: Driver
    asgi: Any
    scheduler: SchedulerFacade
    file_logging: FileLogging
    http_clients: HttpClients
    databases: DatabaseManager
    resources: ApplicationResources
    extension_services: ExtensionServices
    task_owner: TaskOwner
    known_features: tuple[str, ...]
    required_plugin_features: frozenset[Feature]
    onebot_message_handling_enabled: bool = True
    first_connection_platforms: frozenset[Platform] = frozenset(Platform)
    contributions: tuple[PluginContribution, ...] = ()
    resource_startup_hooks: tuple[tuple[str, Any], ...] = ()
    resource_shutdown_hooks: tuple[tuple[str, Any], ...] = ()
    lifecycle: ApplicationLifecycle | None = None
    host_lifecycle: NoneBotHostBinding | None = None
    onebot_transport: OneBotTransport | None = None
    _configured: bool = field(default=False, init=False)
    _installed: bool = field(default=False, init=False)

    def configure(self, contributions: tuple[PluginContribution, ...]) -> None:
        """Finalize application wiring after all contributions are composed."""

        if self._configured:
            msg = "application plugin contributions are already configured"
            raise RuntimeError(msg)

        from ironsbot.core.plugin_install import validate_plugin_contributions

        self.contributions = validate_plugin_contributions(
            contributions,
            required_features=self.required_plugin_features,
        )
        self.resources.contribution_catalog.load(self.contributions)
        self.resources.commands.load(
            self.contributions,
            known_features=self.known_features,
        )
        self.resources.commands.validate_categories()
        self.lifecycle = ApplicationLifecycle.from_contributions(
            self.contributions,
            task_owner=self.task_owner,
            scheduler=self.scheduler,
            resource_startup_hooks=self.resource_startup_hooks,
            resource_shutdown_hooks=self.resource_shutdown_hooks,
        )
        self.lifecycle.first_connection_platforms = self.first_connection_platforms
        if self.resources.qq_official is not None:
            self.resources.qq_official.bind_lifecycle(
                self.lifecycle, spawn=self.task_owner.create
            )
        self._configured = True

    def install(self, router: PortableCommandRouter) -> None:
        if self._installed:
            return
        if not self._configured or self.lifecycle is None:
            msg = "application must be configured before installation"
            raise RuntimeError(msg)
        from ironsbot.integrations.onebot.httpx_exchange import HttpxOneBotExchange
        from ironsbot.integrations.onebot.notice_ingress import OneBotNoticeIngress
        from ironsbot.integrations.onebot.received_messages import (
            OneBotReceivedMessages,
        )
        from ironsbot.integrations.onebot.transport import OneBotTransport

        received = OneBotReceivedMessages(
            self.resources.onebot_admission,
            router,
            self.resources.onebot_messenger,
            nicknames=frozenset(self.driver.config.nickname),
            red_packets=(
                self.resources.red_packet_notice
                if self.onebot_message_handling_enabled
                and any(item.id == "red_packet_notice" for item in self.contributions)
                else None
            ),
        )
        installed = frozenset(item.id for item in self.contributions)
        notices = OneBotNoticeIngress(
            self.resources.onebot_admission,
            self.resources.onebot_messenger,
            self.scheduler,
            self.settings.bot.matcher_priority,
            spawn=self.task_owner.create,
            poke=self.resources.poke_reply if "poke_reply" in installed else None,
            audit=self.resources.team_audit if "team_audit" in installed else None,
            red_packets=received.red_packets,
        )
        self.onebot_transport = OneBotTransport(
            self.driver,
            spawn=self.task_owner.create,
            received=received.handle,
            notices=notices.handle,
            request_http=HttpxOneBotExchange(self.http_clients.origin),
            connections=self.resources.onebot_connections,
            observer=self.lifecycle,
        )
        self.lifecycle.shutdown_hooks = (
            *self.lifecycle.shutdown_hooks,
            ("onebot_transport", self.onebot_transport.close),
        )
        self.host_lifecycle = NoneBotHostBinding(self.driver, self.lifecycle)
        self.host_lifecycle.install()
        self._installed = True
