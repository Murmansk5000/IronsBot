# SPDX-License-Identifier: MIT
"""Compose operations services without coupling them to a chat platform."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from ironsbot.integrations.db_sync.runner import DatabaseSync
from ironsbot.integrations.docker.client import DockerClient
from ironsbot.integrations.headless_seer.client import ClientManager
from ironsbot.integrations.http.server_notice import HttpServerNoticeSource
from ironsbot.integrations.process import terminate_bot_process
from ironsbot.integrations.seer_data.database import SeerDatabase
from ironsbot.services.operations.data_sync import DataSyncService
from ironsbot.services.operations.docker_preflight import DockerStartupPreflightStore
from ironsbot.services.operations.docker_update import DockerUpdateService
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.operations.headless_session import HeadlessSessionFactory
from ironsbot.services.operations.scheduled_restart import ScheduledRestartService
from ironsbot.services.operations.server_status import ServerStatusService
from ironsbot.services.operations.startup import StartupNoticeService

if TYPE_CHECKING:
    from ironsbot.app.lifecycle import TaskOwner
    from ironsbot.config.models.settings import Settings
    from ironsbot.integrations.db_registry import DatabaseManager
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.runtime.cache_paths import CachePaths
    from ironsbot.services.messaging.admin_notice import AdminNoticeService


@dataclass(frozen=True, slots=True)
class OperationsComponents:
    """Operations services assembled from their infrastructure dependencies."""

    data_sync: DataSyncService
    seer_database: SeerDatabase
    headless: HeadlessService
    headless_sessions: HeadlessSessionFactory
    server_status: ServerStatusService
    docker_update: DockerUpdateService
    scheduled_restart: ScheduledRestartService
    startup_notice: StartupNoticeService


def build_operations_components(  # noqa: PLR0913 - application composition boundary
    settings: Settings,
    databases: DatabaseManager,
    cache_paths: CachePaths,
    task_owner: TaskOwner,
    admin_notices: AdminNoticeService,
    http_clients: HttpClients,
) -> OperationsComponents:
    """Build data-sync, headless, and process-management services."""
    database_sync = DatabaseSync(databases, cache_paths=cache_paths)
    for name, source in settings.operations.data_sync.sources.items():
        database_sync.register(name, source)

    seer_database = SeerDatabase(
        databases,
        merge_connected_mintmarks=settings.seer.mintmark.merge_connected,
    )
    headless_operations = HeadlessOperationTracker()
    request_interval_seconds = (
        settings.seer.player.request_protection.base_request_interval_seconds
        if settings.seer.player.request_protection.enabled
        else 0.0
    )
    headless = HeadlessService(
        [
            ClientManager(task_owner.create, operations=headless_operations)
            for _ in settings.headless_accounts
        ],
        settings.operations.headless,
        settings.operations.headless_notice,
        admin_notices,
        accounts=settings.headless_accounts,
        request_interval_seconds=request_interval_seconds,
        spawn=task_owner.create,
    )
    headless_sessions = HeadlessSessionFactory(
        lambda: ClientManager(task_owner.create),
        settings.operations.headless,
        request_interval_seconds=request_interval_seconds,
    )
    return OperationsComponents(
        data_sync=DataSyncService(settings.operations.data_sync, database_sync),
        seer_database=seer_database,
        headless=headless,
        headless_sessions=headless_sessions,
        server_status=ServerStatusService(
            headless,
            HttpServerNoticeSource(http_clients.origin),
            dedicated_sessions=headless_sessions,
        ),
        docker_update=DockerUpdateService(
            settings.operations.docker_update,
            DockerClient(),
            partial(
                terminate_bot_process,
                signal_parent=True,
                reason="admin requested bot restart",
            ),
            handoff_store=DockerStartupPreflightStore(),
        ),
        scheduled_restart=ScheduledRestartService(
            restart_times=(
                tuple(settings.operations.restart.parsed_restart_times)
                if settings.operations.restart.enabled
                else ()
            ),
            grace_seconds=settings.operations.restart.grace_seconds,
            restart_process=partial(
                terminate_bot_process,
                signal_parent=settings.operations.restart.signal_parent,
                reason="scheduled bot restart",
            ),
        ),
        startup_notice=StartupNoticeService(admin_notices),
    )
