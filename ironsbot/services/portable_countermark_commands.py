# SPDX-License-Identifier: MIT
"""Portable countermark stat-rank query operation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.seer.countermark_stat_rank_parsing import (
    parse_countermark_stat_rank_command,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.countermark_stat_rank import (
        CountermarkStatRankService,
    )


def build_portable_countermark_operations(
    service: CountermarkStatRankService,
) -> Mapping[str, PortableOperation]:
    async def query(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del context
        command = parse_countermark_stat_rank_command(text)
        if command is None:
            msg = f"catalog accepted invalid countermark rank command: {text!r}"
            raise ValueError(msg)
        return OutboundMessage.from_text(service.query(command))

    return {"seer.mintmark.rank": query}
