# SPDX-License-Identifier: MIT
"""Build and deliver Bilibili login notices through administrator delivery."""

from __future__ import annotations

import logging
from base64 import b64decode
from typing import TYPE_CHECKING

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart

if TYPE_CHECKING:
    from ironsbot.services.bilibili.login import BiliLoginNotice
    from ironsbot.services.messaging.admin_notice import AdminNoticeService

_LOGGER = logging.getLogger(__name__)


def build_bili_login_outbound_message(notice: BiliLoginNotice) -> OutboundMessage:
    parts: list[TextPart | BinaryImagePart] = [TextPart(notice.text)]
    if notice.qrcode is None:
        return OutboundMessage(tuple(parts))

    if notice.qrcode.image_base64:
        try:
            image = b64decode(notice.qrcode.image_base64, validate=True)
        except ValueError:
            _LOGGER.warning("failed to decode Bilibili login QR image")
        else:
            parts.extend((BinaryImagePart(image, "image/png"), TextPart("\n")))
    elif notice.qrcode.image_error:
        _LOGGER.warning(
            "failed to build Bilibili login QR image: %s",
            notice.qrcode.image_error,
        )
    parts.append(TextPart(notice.qrcode.tip_text))
    return OutboundMessage(tuple(parts))


async def send_bili_login_notice(
    admin_notices: AdminNoticeService,
    notice: BiliLoginNotice,
) -> None:
    await admin_notices.send_message(
        build_bili_login_outbound_message(notice),
        action_name="Bilibili login notice",
        interval_seconds=1.2,
        subscription_key="bili_login_notice",
    )
