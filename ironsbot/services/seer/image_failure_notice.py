# SPDX-License-Identifier: MIT
"""Route Seer image source failures to restricted operational notices."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.seer.images import ImageSourceError

logger = logging.getLogger(__name__)
_MAX_ERROR_LENGTH = 800


@dataclass(frozen=True, slots=True)
class AdminImageFailureReporter:
    admin_notices: AdminNoticeService

    async def __call__(
        self,
        kind: str,
        key: str,
        error: ImageSourceError,
    ) -> None:
        detail = f"{type(error).__name__}: {error}"[:_MAX_ERROR_LENGTH]
        try:
            await self.admin_notices.send(
                "⚠️ 赛尔图片素材获取失败\n"
                f"素材类型：{kind}\n"
                f"资源标识：{key}\n"
                f"异常：{detail}",
                subscription_key="render_crash_notice",
                action_name="Seer image source failure notice",
            )
        except Exception:
            logger.exception(
                "failed to deliver Seer image source failure notice: kind=%s key=%s",
                kind,
                key,
            )
