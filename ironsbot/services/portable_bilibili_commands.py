# SPDX-License-Identifier: MIT
"""Portable operations for interactive Bilibili history queries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from ironsbot.core.authorization import can_manage_group_actor
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.bilibili.commands import parse_bili_push_mode_command
from ironsbot.services.bilibili.outbound_delivery import (
    render_dynamic_content_message,
)
from ironsbot.services.portable_query_sessions import PortableMenuSpec

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from ironsbot.core.authorization import SuperuserPolicy
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.bilibili.dynamic_history import DynamicHistoryRecord
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation, PortableReply

from ironsbot.services.portable_reply import (
    ProgressReporter,
    progress_operation_reply,
)

_LOGGER = logging.getLogger(__name__)


def build_portable_bilibili_operations(
    service: BilibiliService,
    sessions: PortableQuerySessions,
    features: SuperuserPolicy,
    *,
    notify_auth_invalid: Callable[[str], Awaitable[None]],
    refresh_now: Callable[[], Awaitable[str]],
) -> Mapping[str, PortableOperation]:
    """Bind the Bilibili history menu to shared portable query sessions."""

    async def dynamic(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        message = context.message
        try:
            result = await service.query_dynamic_menu(
                actor=message.actor,
                conversation=message.conversation,
            )
        except Exception:
            _LOGGER.exception("portable Bilibili dynamic menu failed")
            return OutboundMessage.from_text("❌ 获取动态列表失败。")

        if result.status == "no_accounts":
            return OutboundMessage.from_text(
                "📭 当前会话没有配置可查询的 B 站账号。"
            )
        if result.status == "auth_invalid":
            await notify_auth_invalid("用户查询动态时发现 B 站登录失效")
            return OutboundMessage.from_text(
                "⚠️ B 站 Cookie 已失效，请超级管理员重新登录。"
            )
        if result.status == "no_history":
            return OutboundMessage.from_text("📭 没有可展示的历史动态。")

        return sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=result.dynamic_ids,
                select=lambda dynamic_id: _dynamic_detail(service, dynamic_id),
                prompt=OutboundMessage.from_text(result.prompt),
                keep_open=True,
                exit_message="已退出动态选择。",
            ),
        )

    return {
        "bilibili.dynamic": dynamic,
        **build_portable_bilibili_management_operations(
            service,
            features,
            refresh_now=refresh_now,
        ),
    }


def build_portable_bilibili_management_operations(
    service: BilibiliService,
    features: SuperuserPolicy,
    *,
    refresh_now: Callable[[], Awaitable[str]],
) -> Mapping[str, PortableOperation]:
    """Build stateless account, push-mode, and refresh operations."""

    async def accounts(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        return OutboundMessage.from_text(
            await service.targets.account_summary(context.message.conversation)
        )

    async def push_mode(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        message = context.message
        if message.conversation.kind == "group" and not can_manage_group_actor(
            features,
            message.actor,
            message.group_role,
        ):
            return OutboundMessage.from_text(
                "❌ 仅群主、管理员或超级管理员可用。"
            )
        parsed = parse_bili_push_mode_command(text)
        if parsed is None:
            return OutboundMessage.from_text("❌ B站推送模式指令格式错误。")
        account_ref, raw_mode = parsed
        return OutboundMessage.from_text(
            await service.targets.update_push_mode(
                message.conversation,
                account_ref,
                raw_mode,
            )
        )

    async def refresh(
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        del text

        async def run(progress: ProgressReporter) -> OutboundMessage:
            await progress("⚡ 正在刷新动态...")
            try:
                _LOGGER.info(
                    "superuser %s manually refreshed Bilibili",
                    context.message.actor.id,
                )
                result = await refresh_now()
            except Exception:
                _LOGGER.exception("manual Bilibili dynamic refresh failed")
                result = "❌ 动态刷新失败。"
            return OutboundMessage.from_text(result)

        return await progress_operation_reply(run)

    return {
        "bilibili.accounts": accounts,
        "bilibili.push_mode": push_mode,
        "bilibili.private_push_mode": push_mode,
        "bilibili.refresh": refresh,
    }


async def _dynamic_detail(
    service: BilibiliService,
    dynamic_id: str,
) -> OutboundMessage:
    try:
        selection = service.select_dynamic([dynamic_id], "1")
        if selection.status != "ok" or selection.record is None:
            return OutboundMessage.from_text(
                "❌ 没找到这条历史动态，请重新发送“动态”。"
            )
        detail = await service.prepare_dynamic_detail(
            cast("DynamicHistoryRecord", selection.record)
        )
        return render_dynamic_content_message(
            detail.item,
            detail.content_override,
        ) or OutboundMessage.from_text("❌ 动态详情解析失败。")
    except Exception:
        _LOGGER.exception("portable Bilibili dynamic detail failed")
        return OutboundMessage.from_text("❌ 动态详情解析失败。")
