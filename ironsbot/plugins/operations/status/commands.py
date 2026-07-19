# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ironsbot.runtime.feature_policy import event_has_feature
from ironsbot.runtime.replies import finish_event_reply

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher

    from ironsbot.services.operations.server_status import (
        ServerStatusResult,
        ServerStatusService,
    )

    from .broadcast import OpenBroadcast

logger = logging.getLogger(__name__)


async def _send_status_result(
    matcher: Matcher,
    event: MessageEvent,
    broadcast: OpenBroadcast,
    result: ServerStatusResult,
) -> None:
    if result.broadcast_opened:
        await broadcast.send(event, now=result.queried_at)
    await finish_event_reply(matcher, event, result.message)


async def handle_normal_status(
    matcher: Matcher,
    event: MessageEvent,
    broadcast: OpenBroadcast,
    service: ServerStatusService,
) -> None:
    if not event_has_feature(broadcast.features, event, "server_status_query"):
        logger.info(
            "normal server status command ignored: "
            "server_status_query feature not allowed"
        )
        return
    await _send_status_result(
        matcher,
        event,
        broadcast,
        await service.query_normal(),
    )


async def handle_admin_status(
    matcher: Matcher,
    event: MessageEvent,
    broadcast: OpenBroadcast,
    service: ServerStatusService,
) -> None:
    await _send_status_result(
        matcher,
        event,
        broadcast,
        await service.query_admin(),
    )
