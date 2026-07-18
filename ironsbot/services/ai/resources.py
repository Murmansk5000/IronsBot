# SPDX-License-Identifier: MIT
from collections.abc import Mapping
from dataclasses import dataclass, field

from ironsbot.config.models.ai import AiConfig
from ironsbot.shared.features import FeatureService
from ironsbot.shared.messaging.admin_notice import AdminNoticeService
from ironsbot.shared.messaging.rate_limits import SlidingWindowRateLimiter


@dataclass(frozen=True, slots=True)
class AiResources:
    config: AiConfig
    features: FeatureService
    admin_notices: AdminNoticeService
    api_key: str
    group_aliases: Mapping[str, int]
    team_resource_commands: tuple[str, ...]
    team_resource_timeout_seconds: float
    history: dict[str, list[dict[str, str]]] = field(default_factory=dict, repr=False)
    notice_limiter: SlidingWindowRateLimiter = field(
        default_factory=SlidingWindowRateLimiter,
        repr=False,
    )

    async def notify_admin_once(
        self,
        key: str,
        message: str,
        *,
        subscription_key: str = "ai_chat_error_notice",
        action_name: str = "AI chat error notice",
    ) -> None:
        if (
            self.notice_limiter.hit(
                "admin_notice",
                key,
                window_seconds=self.config.admin_notice_cooldown_seconds,
                max_events=1,
            )
            < 0
        ):
            return
        await self.admin_notices.send(
            message,
            subscription_key=subscription_key,
            action_name=action_name,
        )
