# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

if TYPE_CHECKING:
    from ironsbot.services.bilibili.login import BiliLoginNotice
    from ironsbot.services.messaging.admin_notice import AdminNoticeService


def build_bili_login_message(notice: BiliLoginNotice) -> str | Message:
    if notice.qrcode is None:
        return notice.text

    message = Message(MessageSegment.text(notice.text))
    if notice.qrcode.image_base64:
        message += MessageSegment.image(
            f"base64://{notice.qrcode.image_base64}"
        )
        message += MessageSegment.text("\n")
    elif notice.qrcode.image_error:
        logger.warning(
            "failed to build Bilibili login QR image: %s",
            notice.qrcode.image_error,
        )
    message += MessageSegment.text(notice.qrcode.tip_text)
    return message


async def send_bili_login_notice(
    admin_notices: AdminNoticeService,
    notice: BiliLoginNotice,
) -> None:
    await admin_notices.send(
        build_bili_login_message(notice),
        action_name="Bilibili login notice",
        interval_seconds=1.2,
        subscription_key="bili_login_notice",
    )
