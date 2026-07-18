# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.plugins.bilibili import auth
from ironsbot.shared.messaging.admin_notice import AdminNoticeService
from ironsbot.shared.messaging.targets import TargetSendSummary
from tests.helpers.bilibili import build_test_bilibili_resources

if TYPE_CHECKING:
    from pathlib import Path

    from nonebot.adapters.onebot.v11 import Bot, Message


@pytest.mark.asyncio
async def test_bili_login_default_notice_uses_admin_notice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: dict[str, object] = {}

    async def fake_send_admin_notice(
        _service: AdminNoticeService,
        message: str | Message,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent.update(message=str(message), **kwargs)
        return TargetSendSummary([], [])

    monkeypatch.setattr(AdminNoticeService, "send", fake_send_admin_notice)

    await auth._send_private_to_superusers(
        build_test_bilibili_resources(tmp_path),
        "请重新登录 B站。",
        bot=cast("Bot", object()),
    )

    assert sent["message"] == "请重新登录 B站。"
    assert sent["action_name"] == "Bilibili login notice"
    assert sent["subscription_key"] == "bili_login_notice"


@pytest.mark.asyncio
async def test_bili_login_explicit_user_notice_stays_private(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: dict[str, object] = {}

    async def fake_send_broadcast_message(
        _delivery: object,
        message: str | Message,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent.update(message=str(message), **kwargs)
        return TargetSendSummary([], [])

    monkeypatch.setattr(
        "ironsbot.shared.messaging.send_broadcast_message",
        fake_send_broadcast_message,
    )

    await auth._send_private_to_superusers(
        build_test_bilibili_resources(tmp_path),
        "Cookie 已刷新。",
        bot=cast("Bot", object()),
        user_ids=[1001],
    )

    assert sent["message"] == "Cookie 已刷新。"
    assert sent["private_user_ids"] == [1001]
    assert "group_ids" not in sent
