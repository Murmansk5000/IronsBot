from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.services.seer.image_failure_notice import AdminImageFailureReporter
from ironsbot.services.seer.images import ImageSourceError

if TYPE_CHECKING:
    from ironsbot.services.messaging.admin_notice import AdminNoticeService


@pytest.mark.asyncio
async def test_image_failure_notice_is_restricted_to_admin_delivery() -> None:
    admin_notices = AsyncMock()
    reporter = AdminImageFailureReporter(
        cast("AdminNoticeService", admin_notices),
    )

    await reporter("pet_body", "1400466", ImageSourceError("network detail"))

    admin_notices.send.assert_awaited_once_with(
        "⚠️ 赛尔图片素材获取失败\n"
        "素材类型：pet_body\n"
        "资源标识：1400466\n"
        "异常：ImageSourceError: network detail",
        subscription_key="render_crash_notice",
        action_name="Seer image source failure notice",
    )
