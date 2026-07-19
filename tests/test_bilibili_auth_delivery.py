# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ironsbot.core.messaging import TargetSendSummary
from ironsbot.plugins.bilibili import auth
from ironsbot.services.bilibili.auth import LoginQrMessageParts
from ironsbot.services.bilibili.login import BiliLoginNotice
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message


@pytest.mark.asyncio
async def test_bili_login_notice_uses_admin_notice(
    monkeypatch: pytest.MonkeyPatch,
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

    await auth.send_bili_login_notice(
        build_test_runtime().admin_notices,
        BiliLoginNotice("请重新登录 B站。"),
    )

    assert sent["message"] == "请重新登录 B站。"
    assert sent["action_name"] == "Bilibili login notice"
    assert sent["subscription_key"] == "bili_login_notice"


def test_bili_login_qrcode_notice_renders_onebot_message() -> None:
    message = auth.build_bili_login_message(
        BiliLoginNotice(
            "请重新登录 B站。\n",
            LoginQrMessageParts(
                tip_text="请扫码",
                image_base64="encoded",
            ),
        )
    )

    rendered = str(message)
    assert rendered.startswith("请重新登录 B站。")
    assert "base64://encoded" in rendered
    assert rendered.endswith("请扫码")
