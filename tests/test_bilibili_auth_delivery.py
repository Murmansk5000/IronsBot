# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.integrations.onebot import bilibili_auth as auth
from ironsbot.services.bilibili.auth import LoginQrMessageParts
from ironsbot.services.bilibili.login import BiliLoginNotice
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from tests.helpers.runtime import build_test_runtime


@pytest.mark.asyncio
async def test_bili_login_notice_uses_admin_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, object] = {}

    async def fake_send_admin_notice(
        _service: AdminNoticeService,
        message: OutboundMessage,
        **kwargs: object,
    ) -> object:
        sent.update(message=message, **kwargs)
        return object()

    monkeypatch.setattr(
        AdminNoticeService,
        "send_message",
        fake_send_admin_notice,
    )

    await auth.send_bili_login_notice(
        build_test_runtime().admin_notices,
        BiliLoginNotice("请重新登录 B站。"),
    )

    assert sent["message"] == OutboundMessage((TextPart("请重新登录 B站。"),))
    assert sent["action_name"] == "Bilibili login notice"
    assert sent["subscription_key"] == "bili_login_notice"


def test_bili_login_qrcode_notice_builds_platform_neutral_message() -> None:
    message = auth.build_bili_login_outbound_message(
        BiliLoginNotice(
            "请重新登录 B站。\n",
            LoginQrMessageParts(
                tip_text="请扫码",
                image_base64="cG5n",
            ),
        )
    )

    assert message == OutboundMessage(
        (
            TextPart("请重新登录 B站。\n"),
            BinaryImagePart(b"png", "image/png"),
            TextPart("\n"),
            TextPart("请扫码"),
        )
    )
