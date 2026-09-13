# SPDX-License-Identifier: MIT
"""Portable operations for status and configured meeting queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.messaging.meeting import build_meeting_reply

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.operations.server_status import ServerStatusService
    from ironsbot.services.portable_reply import PortableOperation


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
        del text, context
        reply = build_meeting_reply(number, template)
        if reply is None:
            reply = (
                "会议号还没有配置，请在 messaging.meeting.number 中填写腾讯会议号。"
            )
        return OutboundMessage.from_text(reply)

    return {
        "meeting": meeting,
    }
