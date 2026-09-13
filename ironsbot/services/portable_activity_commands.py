# SPDX-License-Identifier: MIT
"""Portable command operations for activity queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.portable_reply import PortableOperation


def build_portable_activity_operations(
    service: ActivityService,
) -> Mapping[str, PortableOperation]:
    """Bind activity command IDs to the shared domain service."""

    async def current(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text, context
        return OutboundMessage.from_text(await service.build_current_message())

    async def ending(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text, context
        return OutboundMessage.from_text(
            await service.build_current_message(soon_only=True)
        )

    async def newly_added(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text, context
        return OutboundMessage.from_text(await service.build_newly_added_message())

    return {
        "activity.current": current,
        "activity.ending": ending,
        "activity.new": newly_added,
    }
