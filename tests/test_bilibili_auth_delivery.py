# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.plugins.bilibili import auth
from ironsbot.shared.messaging.targets import TargetSendSummary

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot, Message


@pytest.mark.asyncio
async def test_bili_login_default_notice_uses_admin_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}

    async def fake_send_admin_notice(
        message: str | Message,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent.update(message=str(message), **kwargs)
        return TargetSendSummary([], [])

    monkeypatch.setattr(auth, "send_admin_notice", fake_send_admin_notice)

    await auth._send_private_to_superusers(
        "请重新登录 B站。",
        bot=cast("Bot", object()),
    )

    assert sent["message"] == "请重新登录 B站。"
    assert sent["action_name"] == "Bilibili login notice"
    assert sent["subscription_key"] == "bili_login_notice"


@pytest.mark.asyncio
async def test_bili_login_explicit_user_notice_stays_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}

    async def fake_send_broadcast_message(
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
        "Cookie 已刷新。",
        bot=cast("Bot", object()),
        user_ids=[1001],
    )

    assert sent["message"] == "Cookie 已刷新。"
    assert sent["private_user_ids"] == [1001]
    assert "group_ids" not in sent
