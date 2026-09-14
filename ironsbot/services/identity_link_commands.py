# SPDX-License-Identifier: MIT
"""Shared command presentation for explicit cross-platform identity links."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.affix_commands import AffixCommand
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import Platform
from ironsbot.services.identity_linking import IdentityLinkingError

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.integrations.storage.identity_links import (
        CrossPlatformIdentityLink,
    )
    from ironsbot.services.identity_linking import IdentityLinkingService
    from ironsbot.services.portable_reply import PortableOperation

IDENTITY_LINK_BEGIN = AffixCommand(("关联官方账号",), ())
IDENTITY_LINK_CONFIRM = AffixCommand(("关联账号",), ())
_MASK_EDGE_LENGTH = 4


class IdentityLinkCommandError(RuntimeError):
    @classmethod
    def begin_not_parsed(cls) -> IdentityLinkCommandError:
        return cls("identity begin command was not parsed")

    @classmethod
    def confirmation_not_parsed(cls) -> IdentityLinkCommandError:
        return cls("identity confirmation command was not parsed")


def build_portable_identity_link_operations(
    commands: IdentityLinkCommands,
) -> dict[str, PortableOperation]:
    return {
        "seer.player.identity.confirm": commands.portable_confirm,
        "seer.player.identity.status": commands.portable_status,
        "seer.player.identity.revoke": commands.portable_revoke,
    }


@dataclass(frozen=True, slots=True)
class IdentityLinkCommands:
    service: IdentityLinkingService

    async def begin_text(self, text: str, context: MessageInputContext) -> str:
        parsed = IDENTITY_LINK_BEGIN(text)
        if parsed is None:
            raise IdentityLinkCommandError.begin_not_parsed()
        try:
            challenge = await self.service.begin(
                context.message.actor,
                parsed.argument,
            )
        except IdentityLinkingError as exc:
            return str(exc)
        return (
            f"关联令牌：{challenge.token}\n"
            f"请在官方机器人“{challenge.account.alias}”中发送：\n"
            f"关联账号 {challenge.token}\n"
            "令牌短时有效且只能使用一次。"
        )

    async def confirm_text(
        self,
        text: str,
        context: MessageInputContext,
    ) -> str:
        parsed = IDENTITY_LINK_CONFIRM(text)
        if parsed is None:
            raise IdentityLinkCommandError.confirmation_not_parsed()
        try:
            await self.service.confirm(context.message.actor, parsed.argument)
        except IdentityLinkingError as exc:
            return str(exc)
        return "账号关联成功。现在两个接入端会识别为同一位用户。"

    async def status_text(
        self,
        context: MessageInputContext,
    ) -> str:
        links = await self.service.links_for(context.message.actor)
        if not links:
            return "当前账号尚未建立跨平台关联。"
        if context.message.actor.platform is Platform.ONEBOT:
            lines = ["已关联的 QQ 官方身份："]
            lines.extend(_format_official_link(link) for link in links)
            return "\n".join(lines)
        return f"当前官方身份已关联 QQ：{_mask_qq_id(links[0].onebot_qq_id)}。"

    async def revoke_text(
        self,
        context: MessageInputContext,
    ) -> str:
        count = await self.service.revoke(context.message.actor)
        if count == 0:
            return "当前账号没有可解除的跨平台关联。"
        return f"已解除 {count} 条跨平台账号关联。"

    async def portable_confirm(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        return OutboundMessage.from_text(await self.confirm_text(text, context))

    async def portable_status(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        return OutboundMessage.from_text(await self.status_text(context))

    async def portable_revoke(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        return OutboundMessage.from_text(await self.revoke_text(context))


def _format_official_link(link: CrossPlatformIdentityLink) -> str:
    kind = "群成员" if link.official.kind == "member" else "私聊用户"
    return f"- {link.official.app_id} / {kind} / {_mask_openid(link.official.openid)}"


def _mask_qq_id(qq_id: str) -> str:
    visible = qq_id[-4:]
    return "*" * max(0, len(qq_id) - len(visible)) + visible


def _mask_openid(openid: str) -> str:
    if len(openid) <= _MASK_EDGE_LENGTH * 2:
        return "*" * len(openid)
    return f"{openid[:_MASK_EDGE_LENGTH]}...{openid[-_MASK_EDGE_LENGTH:]}"
