# SPDX-License-Identifier: MIT
from __future__ import annotations

import time
from dataclasses import dataclass

from ironsbot.config.loader import get_app_config
from ironsbot.shared.features import feature_service
from ironsbot.shared.messaging.rate_limits import (
    hit_sliding_window_rate_limit,
    sliding_window_rate_limiter,
)

ADMIN_NOTICE_FEATURE = "admin_notice"
OUTBOUND_RATE_LIMIT_NAMESPACE = "messaging.outbound.group"


@dataclass(frozen=True, slots=True)
class OutboundRateLimitDecision:
    allowed: bool
    cooldown_message: str | None = None


def reset_outbound_rate_limit_state() -> None:
    sliding_window_rate_limiter.clear(OUTBOUND_RATE_LIMIT_NAMESPACE)


def _is_limited_group(group_id: int) -> bool:
    return not feature_service.group_has_feature(group_id, ADMIN_NOTICE_FEATURE)


def check_group_outbound_rate_limit(
    group_id: int | None,
    *,
    now: float | None = None,
) -> OutboundRateLimitDecision:
    if group_id is None:
        return OutboundRateLimitDecision(allowed=True)

    config = get_app_config().message.outbound_rate_limit
    if not config.enabled or not _is_limited_group(group_id):
        return OutboundRateLimitDecision(allowed=True)

    remaining = hit_sliding_window_rate_limit(
        OUTBOUND_RATE_LIMIT_NAMESPACE,
        group_id,
        window_seconds=config.window_seconds,
        max_events=config.max_messages,
        now=time.monotonic() if now is None else now,
    )
    if remaining < 0:
        return OutboundRateLimitDecision(allowed=False)

    if remaining == 0:
        return OutboundRateLimitDecision(
            allowed=True,
            cooldown_message=config.cooldown_message,
        )
    return OutboundRateLimitDecision(allowed=True)
