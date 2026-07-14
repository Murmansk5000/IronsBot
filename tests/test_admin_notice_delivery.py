# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from ironsbot.shared.messaging import admin_notice
from ironsbot.shared.messaging.targets import TargetSendSummary


def test_admin_notice_targets_use_superusers_and_admin_notice_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admin_notice, "get_superuser_ids", lambda: {2002, 1001})
    monkeypatch.setattr(
        admin_notice,
        "groups_for_feature",
        lambda feature: [3003] if feature == "admin_notice" else [4004],
    )

    targets = admin_notice.admin_notice_targets()

    assert targets.private_user_ids == [1001, 2002]
    assert targets.group_ids == [3003]


@pytest.mark.asyncio
async def test_send_admin_notice_uses_admin_notice_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}
    monkeypatch.setattr(admin_notice, "get_superuser_ids", lambda: {1001})
    monkeypatch.setattr(admin_notice, "groups_for_feature", lambda _feature: [3003])
    monkeypatch.setattr(admin_notice, "get_first_onebot_bot", lambda: None)

    async def fake_send_broadcast_message(
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

    await admin_notice.send_admin_notice(
        "AI聊天接口异常。",
        subscription_key="ai_chat_error_notice",
        action_name="AI chat error notice",
    )

    assert sent == {
        "message": "AI聊天接口异常。",
        "private_user_ids": [1001],
        "group_ids": [3003],
        "action_name": "AI chat error notice",
        "subscription_key": "ai_chat_error_notice",
    }


@pytest.mark.asyncio
async def test_send_admin_notice_skips_when_no_admin_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def no_superusers() -> set[int]:
        return set()

    monkeypatch.setattr(admin_notice, "get_superuser_ids", no_superusers)
    monkeypatch.setattr(admin_notice, "groups_for_feature", lambda _feature: [])

    async def fake_send_broadcast_message(*_args: object, **_kwargs: object):
        nonlocal called
        called = True
        return TargetSendSummary([], [])

    monkeypatch.setattr(
        admin_notice,
        "send_broadcast_message",
        fake_send_broadcast_message,
    )

    summary = await admin_notice.send_admin_notice(
        "AI聊天接口异常。",
        subscription_key="ai_chat_error_notice",
        action_name="AI chat error notice",
    )

    assert summary.succeeded == []
    assert summary.failed == []
    assert not called
