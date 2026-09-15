# SPDX-License-Identifier: MIT
"""Explicitly enabled QQ Official identity inspection for deployment setup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import CommandContract
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import Platform

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext

OFFICIAL_IDENTITY_INFO_COMMAND_ID = "about.official_identity_info"


class OfficialIdentityInfoError(ValueError):
    @classmethod
    def unsupported_platform(cls) -> OfficialIdentityInfoError:
        return cls("identity information is unavailable for this platform")


def official_identity_info_command_contracts() -> tuple[CommandContract, ...]:
    return (
        CommandContract(
            id=OFFICIAL_IDENTITY_INFO_COMMAND_ID,
            plugin_id="about",
            section="设置",
            examples=("官方身份",),
            description="查看当前会话用于开发配置的官方平台标识",
            features_any=("qq_official_identity_info",),
            platforms=frozenset({Platform.QQ_OFFICIAL}),
        ),
    )


async def official_identity_info(
    text: str,
    context: MessageInputContext,
) -> OutboundMessage:
    del text
    message = context.message
    if message.actor.platform is not Platform.QQ_OFFICIAL:
        raise OfficialIdentityInfoError.unsupported_platform()
    if message.conversation.kind == "private":
        return OutboundMessage.from_text(
            "当前官方用户标识：\n"
            f"user_openid = {message.actor.id}\n"
            "仅用于本机开发配置，请勿公开转发。"
        )
    return OutboundMessage.from_text(
        "当前官方群聊标识：\n"
        f"group_openid = {message.conversation.id}\n"
        f"member_openid = {message.actor.id}\n"
        "仅用于本机开发配置，请勿公开转发。"
    )
