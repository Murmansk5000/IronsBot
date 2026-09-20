# SPDX-License-Identifier: MIT
"""Portable operations for status and configured meeting queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage, address_message_to
from ironsbot.services.messaging.meeting import build_meeting_reply
from ironsbot.services.operations.docker_update import (
    DOCKER_MAINTENANCE_OPTIONS,
    DockerMaintenanceOption,
    docker_maintenance_menu_text,
)
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.portable_reply import PortableReply, progress_operation_reply

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.operations.data_sync import (
        DataSyncService,
        ManualDataSyncOption,
    )
    from ironsbot.services.operations.docker_update import DockerUpdateService
    from ironsbot.services.operations.server_status import ServerStatusService
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation, ProgressReporter


def build_portable_data_sync_operations(
    service: DataSyncService,
    sessions: PortableQuerySessions,
) -> Mapping[str, PortableOperation]:
    """Bind data maintenance without duplicating its checks or action menu."""

    owner = _PortableDataSyncOperations(service, sessions)
    return {
        "db_sync.update": owner.update,
        "db_sync.force_update": owner.force_update,
    }


@dataclass(frozen=True, slots=True)
class _PortableDataSyncOperations:
    service: DataSyncService
    sessions: PortableQuerySessions

    async def update(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        del text
        return await self._prepare(force=False, context=context)

    async def force_update(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        del text
        return await self._prepare(force=True, context=context)

    async def _prepare(
        self,
        *,
        force: bool,
        context: MessageInputContext,
    ) -> PortableReply:
        async def prepare(progress: ProgressReporter) -> str | OutboundMessage:
            message, should_run = await self.service.prepare_manual(
                force=force,
                progress=progress,
            )
            if not should_run:
                return message

            async def select(
                option: ManualDataSyncOption,
                _context: MessageInputContext,
            ) -> PortableReply:
                async def run(action_progress: ProgressReporter) -> str:
                    return await self.service.run_manual(
                        action=option.action,
                        force=force,
                        progress=action_progress,
                    )

                return await progress_operation_reply(run)

            return self.sessions.offer_menu(
                context,
                PortableMenuSpec(
                    choices=self.service.manual_options(force=force),
                    select=select,
                    prompt=OutboundMessage.from_text(message),
                    exit_message="已取消更新。",
                ),
            )

        return await progress_operation_reply(prepare)


def build_portable_docker_operations(
    service: DockerUpdateService,
    sessions: PortableQuerySessions,
) -> Mapping[str, PortableOperation]:
    """Bind Docker maintenance with restart work gated by reply delivery."""

    async def check_image(
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        del text, context

        async def check(progress: ProgressReporter) -> str:
            return await service.check_image_update(progress=progress)

        return await progress_operation_reply(check)

    async def open_maintenance(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text

        async def select(
            option: DockerMaintenanceOption,
            _context: MessageInputContext,
        ) -> PortableReply:
            message, action = await service.prepare_maintenance(option.choice)

            async def execute() -> OutboundMessage:
                await service.execute_restart(action)
                return OutboundMessage.from_text("机器人维护操作已提交。")

            return PortableReply(
                OutboundMessage.from_text(message),
                follow_up=execute,
            )

        return sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=DOCKER_MAINTENANCE_OPTIONS,
                select=select,
                prompt=OutboundMessage.from_text(docker_maintenance_menu_text()),
                exit_message="已退出机器人维护。",
            ),
        )

    return {
        "docker_update.restart": open_maintenance,
        "docker_update.image_update": open_maintenance,
        "docker_update.image_check": check_image,
    }


def build_portable_server_status_operations(
    server_status: ServerStatusService,
) -> Mapping[str, PortableOperation]:
    """Bind server-status command IDs to the shared status service."""

    async def normal_status(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text, context
        return OutboundMessage.from_text((await server_status.query_normal()).message)

    async def admin_status(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text, context
        return OutboundMessage.from_text((await server_status.query_admin()).message)

    async def headless_instances(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text, context
        result = await server_status.query_headless_instances()
        return OutboundMessage.from_text(result.message)

    return {
        "server_status.query": normal_status,
        "server_status.admin_query": admin_status,
        "server_status.headless_instances": headless_instances,
    }


def build_portable_meeting_operations(
    number: str,
    template: str,
) -> Mapping[str, PortableOperation]:
    """Bind the configured meeting command to its shared formatter."""

    async def meeting(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        reply = build_meeting_reply(number, template)
        if reply is None:
            reply = "会议号还没有配置，请在 messaging.meeting.number 中填写腾讯会议号。"
        return address_message_to(
            OutboundMessage.from_text(reply),
            context.member_mentions,
        )

    return {
        "meeting": meeting,
    }
