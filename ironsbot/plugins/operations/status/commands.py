# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.replies import finish_event_reply

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher

    from ironsbot.core.features import FeatureService
    from ironsbot.services.operations.server_status import (
        ServerStatusService,
    )

logger = logging.getLogger(__name__)


async def handle_normal_status(
    matcher: Matcher,
    event: MessageEvent,
    features: FeatureService,
    service: ServerStatusService,
) -> None:
    if not event_is_feature_allowed(
        features,
        event,
        "server_status_query",
    ):
        logger.info(
            "normal server status command ignored: "
            "server_status_query feature not allowed"
        )
        return
    result = await service.query_normal()
    await finish_event_reply(matcher, event, result.message)


async def handle_admin_status(
    matcher: Matcher,
    event: MessageEvent,
    service: ServerStatusService,
) -> None:
    result = await service.query_admin()
    await finish_event_reply(matcher, event, result.message)
