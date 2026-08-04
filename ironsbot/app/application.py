# SPDX-License-Identifier: MIT
"""Configured application runtime assembled by the composition root."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver

    from ironsbot.app.file_logging import FileLogging
    from ironsbot.app.resources import ApplicationResources
    from ironsbot.config.models.settings import Settings
    from ironsbot.core.features import Feature
    from ironsbot.integrations.db_registry import DatabaseManager
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.integrations.scheduler.facade import SchedulerFacade
    from ironsbot.runtime.matchers import MatcherRegistry, PromptSessionManager
    from ironsbot.runtime.plugins import PluginContribution


@dataclass(slots=True)
class Application:
    """Own process resources after a NoneBot manifest supplies contributions."""

    settings: Settings
    driver: Driver
    asgi: Any
    scheduler: SchedulerFacade
    file_logging: FileLogging
    http_clients: HttpClients
    databases: DatabaseManager
    prompt_sessions: PromptSessionManager
    resources: ApplicationResources
    matchers: MatcherRegistry
    task_owner: TaskOwner
    known_features: tuple[str, ...]
    required_plugin_features: frozenset[Feature]
    contributions: tuple[PluginContribution, ...] = ()
    resource_shutdown_hooks: tuple[tuple[str, Any], ...] = ()
    lifecycle: ApplicationLifecycle | None = None
    _configured: bool = field(default=False, init=False)
    _installed: bool = field(default=False, init=False)

    def configure(self, contributions: tuple[PluginContribution, ...]) -> None:
        """Finalize application wiring after standard NoneBot plugin loading."""

        if self._configured:
            msg = "application plugin contributions are already configured"
            raise RuntimeError(msg)

        from ironsbot.runtime.plugins import validate_plugin_contributions

        self.contributions = validate_plugin_contributions(
            contributions,
            required_features=self.required_plugin_features,
        )
        self.resources.contribution_catalog.load(self.contributions)
        self.resources.commands.load(
            self.contributions,
            known_features=self.known_features,
        )
        self.lifecycle = ApplicationLifecycle.from_contributions(
            self.driver,
            self.contributions,
            task_owner=self.task_owner,
            resource_shutdown_hooks=self.resource_shutdown_hooks,
        )
        self._configured = True

    def install(self) -> None:
        if self._installed:
            return
        if not self._configured or self.lifecycle is None:
            msg = "application must be configured before installation"
            raise RuntimeError(msg)
        for contribution in self.contributions:
            if contribution.install is not None:
                contribution.install(self.matchers)
        self.matchers.validate_command_catalog(self.resources.commands)
        self.matchers.install_postprocessor()
        self.lifecycle.install()
        self._installed = True
