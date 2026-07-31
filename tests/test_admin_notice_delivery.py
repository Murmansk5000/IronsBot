# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.features import FeatureConfig, FeatureService
from ironsbot.core.messaging import TargetSendSummary
from ironsbot.services.messaging.admin_notice import AdminNoticeService

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import Any

    from ironsbot.services.messaging.delivery import MessageDelivery


class FakeDelivery:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def broadcast(  # noqa: PLR0913
        self,
        message: Any,
        *,
        private_user_ids: Iterable[int] = (),
        group_ids: Iterable[int] = (),
        group_at_user_ids: Iterable[int] = (),
        bot: Any | None = None,
        action_name: str = "message action",
        interval_seconds: float = 1.5,
        message_limiter: Callable[[Any, int | None], Any] | None = None,
        subscription_key: str | None = None,
    ) -> TargetSendSummary:
        self.calls.append(
            {
                "message": message,
                "private_user_ids": list(private_user_ids),
                "group_ids": list(group_ids),
                "group_at_user_ids": list(group_at_user_ids),
                "bot": bot,
                "action_name": action_name,
                "interval_seconds": interval_seconds,
                "message_limiter": message_limiter,
                "subscription_key": subscription_key,
            }
        )
        return TargetSendSummary([], [])

def _service(
    *,
    with_targets: bool = True,
) -> tuple[AdminNoticeService, FakeDelivery]:
    feature_config = FeatureConfig(
        group_policy={"3003": ["admin_notice"]} if with_targets else {},
    )
    delivery = FakeDelivery()
    return (
        AdminNoticeService(
            FeatureService(
                feature_config,
                frozenset((2002, 1001) if with_targets else ()),
            ),
            cast("MessageDelivery", delivery),
        ),
        delivery,
    )


def test_admin_notice_targets_use_superusers_and_admin_notice_groups() -> None:
    service, _delivery = _service()
    targets = service.targets()

    assert targets.private_user_ids == [1001, 2002]
    assert targets.group_ids == [3003]


@pytest.mark.asyncio
async def test_send_admin_notice_uses_admin_notice_targets(
) -> None:
    service, delivery = _service()
    await service.send(
        "AI聊天接口异常。",
        subscription_key="ai_chat_error_notice",
        action_name="AI chat error notice",
    )

    assert delivery.calls == [{
        "message": "AI聊天接口异常。",
        "private_user_ids": [1001, 2002],
        "group_ids": [3003],
        "group_at_user_ids": [],
        "action_name": "AI chat error notice",
        "subscription_key": "ai_chat_error_notice",
        "bot": None,
        "interval_seconds": 1.5,
        "message_limiter": None,
    }]


@pytest.mark.asyncio
async def test_send_admin_notice_skips_when_no_admin_targets(
) -> None:
    service, delivery = _service(with_targets=False)
    summary = await service.send(
        "AI聊天接口异常。",
        subscription_key="ai_chat_error_notice",
        action_name="AI chat error notice",
    )

    assert summary.succeeded == []
    assert summary.failed == []
    assert delivery.calls == []


@pytest.mark.asyncio
async def test_private_superuser_notice_never_uses_admin_notice_groups() -> None:
    service, delivery = _service()

    await service.send_private_to_superusers(
        "幸运橱窗命中关注皮肤。",
        subscription_key="private_skin_window",
        action_name="private skin window notice",
    )

    assert delivery.calls == [{
        "message": "幸运橱窗命中关注皮肤。",
        "private_user_ids": [1001, 2002],
        "group_ids": [],
        "group_at_user_ids": [],
        "action_name": "private skin window notice",
        "subscription_key": "private_skin_window",
        "bot": None,
        "interval_seconds": 1.5,
        "message_limiter": None,
    }]
