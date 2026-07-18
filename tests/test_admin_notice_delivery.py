# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.shared.messaging import admin_notice
from ironsbot.shared.messaging.targets import TargetSendSummary
from tests.helpers.runtime import build_test_runtime


def _service(*, with_targets: bool = True) -> admin_notice.AdminNoticeService:
    feature_config = FeatureConfig(
        group_policy={"3003": ["admin_notice"]} if with_targets else {},
    )
    return build_test_runtime(
        feature_config=feature_config,
        superuser_ids=(2002, 1001) if with_targets else (),
    ).admin_notices


def test_admin_notice_targets_use_superusers_and_admin_notice_groups() -> None:
    targets = _service().targets()

    assert targets.private_user_ids == [1001, 2002]
    assert targets.group_ids == [3003]


@pytest.mark.asyncio
async def test_send_admin_notice_uses_admin_notice_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}

    async def fake_send_broadcast_message(
        _delivery: object,
        message: str,
        *,
        private_user_ids: list[int],
        group_ids: list[int],
        action_name: str,
        subscription_key: str,
        **_kwargs: object,
    ) -> TargetSendSummary:
        sent.update(
            message=message,
            private_user_ids=private_user_ids,
            group_ids=group_ids,
            action_name=action_name,
            subscription_key=subscription_key,
        )
        return TargetSendSummary([], [])

    monkeypatch.setattr(
        admin_notice,
        "send_broadcast_message",
        fake_send_broadcast_message,
    )

    await _service().send(
        "AI聊天接口异常。",
        subscription_key="ai_chat_error_notice",
        action_name="AI chat error notice",
    )

    assert sent == {
        "message": "AI聊天接口异常。",
        "private_user_ids": [1001, 2002],
        "group_ids": [3003],
        "action_name": "AI chat error notice",
        "subscription_key": "ai_chat_error_notice",
    }


@pytest.mark.asyncio
async def test_send_admin_notice_skips_when_no_admin_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_send_broadcast_message(*_args: object, **_kwargs: object):
        nonlocal called
        called = True
        return TargetSendSummary([], [])

    monkeypatch.setattr(
        admin_notice,
        "send_broadcast_message",
        fake_send_broadcast_message,
    )

    summary = await _service(with_targets=False).send(
        "AI聊天接口异常。",
        subscription_key="ai_chat_error_notice",
        action_name="AI chat error notice",
    )

    assert summary.succeeded == []
    assert summary.failed == []
    assert not called
