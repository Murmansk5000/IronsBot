# SPDX-License-Identifier: MIT
"""Configured application runtime assembled by the composition root."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

from ironsbot.app.host import application_lifespan
from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.core.platform import Platform

if TYPE_CHECKING:
    from fastapi import FastAPI

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
    from ironsbot.services.messaging.delivery_recovery import ProactiveRecovery
    from ironsbot.services.portable_commands import PortableCommandRouter


@dataclass(slots=True)
class Application:
    """Own process resources and explicitly composed business contributions."""

    settings: Settings
    asgi: FastAPI
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
    onebot_transport: OneBotTransport | None = None
    push_recovery: ProactiveRecovery | None = None
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
        if self.push_recovery is not None:
            self.lifecycle.startup_hooks = (
                *self.lifecycle.startup_hooks,
                ("push_recovery", self.push_recovery.start),
            )
            self.lifecycle.bot_connect_hooks = (
                *self.lifecycle.bot_connect_hooks,
                ("push_recovery", self.push_recovery.connected),
            )
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
        if self.settings.bot.onebot.enabled:
            self._install_onebot(router, self.lifecycle)
        self.asgi.router.lifespan_context = partial(
            application_lifespan, self.lifecycle
        )
        self._installed = True

    def _install_onebot(
        self, router: PortableCommandRouter, lifecycle: ApplicationLifecycle
    ) -> None:
        from ironsbot.integrations.onebot.asgi import OneBotASGI
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
            nicknames=frozenset(self.settings.bot.onebot.nicknames),
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
            self.settings.bot.onebot.notice_priority,
            spawn=self.task_owner.create,
            poke=self.resources.poke_reply if "poke_reply" in installed else None,
            audit=self.resources.team_audit if "team_audit" in installed else None,
            red_packets=received.red_packets,
        )
        self.onebot_transport = OneBotTransport(
            config=self.settings.bot.onebot,
            access_token=self.settings.bot.onebot_token or None,
            spawn=self.task_owner.create,
            received=received.handle,
            notices=notices.handle,
            request_http=HttpxOneBotExchange(self.http_clients.origin),
            connections=self.resources.onebot_connections,
            observer=lifecycle,
        )
        OneBotASGI(self.onebot_transport).install(self.asgi)
        lifecycle.resource_startup_hooks = (
            *lifecycle.resource_startup_hooks,
            ("onebot_transport", self.onebot_transport.start),
        )
        lifecycle.shutdown_hooks = (
            *lifecycle.shutdown_hooks,
            ("onebot_transport", self.onebot_transport.close),
        )
