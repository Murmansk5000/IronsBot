# SPDX-License-Identifier: MIT
"""Shared data-version, preview and season-countdown execution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.commands import command_text_matches
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
from ironsbot.services.seer.external_references import SeerInfoReference

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.data_queries import SeerDataQueryService
    from ironsbot.services.seer.external_references import SeerInfoReferences


def build_portable_data_operation(
    service: SeerDataQueryService,
    references: SeerInfoReferences | None = None,
) -> PortableOperation:
    async def execute(text: str, context: MessageInputContext) -> OutboundMessage:
        del context
        if command_text_matches(text, DATA_VERSION_COMMANDS):
            result = await service.data_version()
        elif command_text_matches(text, SEASON_COUNTDOWN_COMMANDS):
            result = await service.season_countdown()
        elif command_text_matches(text, WEEKLY_PREVIEW_COMMANDS):
            result = await service.weekly_preview()
        else:
            msg = "unsupported data query"
            raise ValueError(msg)
        if isinstance(result, OutboundMessage):
            return result
        if isinstance(result, DataQueryImageReply):
            url = (
                None
                if references is None
                else references.url_for(SeerInfoReference.WEEKLY_PREVIEW)
            )
            return result.to_outbound(reference_url=url)
        return OutboundMessage.from_text(result)

    return execute
