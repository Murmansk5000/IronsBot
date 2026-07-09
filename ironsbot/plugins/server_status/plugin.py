# SPDX-License-Identifier: MIT
# ruff: noqa: TC001, TC002
"""Server status feature plugin implementation."""

from __future__ import annotations

from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent

from ironsbot.plugins.headless_seer_notice.service import login_headless_client
from ironsbot.plugins.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.shared.plugin_system import PluginContext

from .broadcast import broadcast_opened
from .matchers import (
    admin_server_status_matcher,
    bot_restart_matcher,
    disabled_bare_admin_status_matcher,
    docker_update_matcher,
    normal_server_status_matcher,
)
from .metadata import SERVER_STATUS_PLUGIN_NAME, __plugin_meta__
from .notice import (
    _build_fetch_failed_reply,
    _build_no_notice_reply,
    _build_notice_reply,
    _build_open_reply,
    _now,
    fetch_server_notice_text,
)
from .restart_command import handle_restart_command
from .status import HeadlessStatus
from .status import get_headless_status as _get_headless_status


class ServerStatusPlugin:
    name = SERVER_STATUS_PLUGIN_NAME
    feature = "server_status_query"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        if context.action == "normal":
            await self._handle_normal(
                context.matcher or normal_server_status_matcher,
                event,
            )
            return
        if context.action == "disabled_bare_admin":
            await finish_event_reply(
                context.matcher or disabled_bare_admin_status_matcher,
                event,
                str(__plugin_meta__.usage or "暂无详细帮助。"),
            )
            return
        if context.action == "admin":
            await self._handle_admin(
                context.matcher or admin_server_status_matcher,
                event,
            )
            return
        if context.action == "restart":
            await self._handle_restart(context.matcher or bot_restart_matcher, event)
            return
        if context.action == "docker_update":
            await self._handle_restart(context.matcher or docker_update_matcher, event)
            return

    async def _handle_normal(self, matcher: Any, event: MessageEvent) -> None:
        if not is_event_feature_allowed(event, "server_status_query"):
            logger.info(
                "normal server status command ignored: "
                "server_status_query feature not allowed"
            )
            return

        now = _now()
        headless_status = _get_headless_status()
        if headless_status.connected:
            await mark_headless_available(source="开服了吗")
        else:
            await mark_headless_unavailable(headless_status.reason, source="开服了吗")

        try:
            notice_text = await fetch_server_notice_text()
        except Exception as e:  # noqa: BLE001
            logger.opt(exception=True).warning("开服公告读取失败")
            if headless_status.connected:
                await broadcast_opened(event, now=now)
            await finish_event_reply(
                matcher,
                event,
                _build_fetch_failed_reply(now, e, headless_status=headless_status),
                mention_sender=True,
            )
            return

        if headless_status.connected:
            await broadcast_opened(event, now=now)
            await finish_event_reply(
                matcher,
                event,
                _build_open_reply(now, notice_text=notice_text),
                mention_sender=True,
            )
            return

        if notice_text:
            await finish_event_reply(
                matcher,
                event,
                _build_notice_reply(notice_text),
                mention_sender=True,
            )
            return

        await finish_event_reply(
            matcher,
            event,
            _build_no_notice_reply(now, headless_status=headless_status),
            mention_sender=True,
        )

    async def _handle_admin(self, matcher: Any, event: MessageEvent) -> None:
        now = _now()
        lines = ["🛠【管理员开服查询】"]
        headless_status = _get_headless_status()
        if headless_status.connected:
            await mark_headless_available(source="/开服查询")
            lines.append("无头状态：已登录游戏服务器。")
        else:
            await mark_headless_unavailable(headless_status.reason, source="/开服查询")
            lines.append(f"无头状态：未登录（{headless_status.reason}）。")
            try:
                user_id = await login_headless_client()
            except Exception as e:  # noqa: BLE001
                logger.opt(exception=True).warning("管理员开服查询触发无头重连失败")
                headless_status = HeadlessStatus(connected=False, reason=str(e))
                await mark_headless_unavailable(str(e), source="/开服查询重连")
                lines.append(f"重连结果：失败：{e}")
            else:
                headless_status = HeadlessStatus(connected=True)
                await mark_headless_available(source="/开服查询重连", user_id=user_id)
                lines.append(f"重连结果：已登录米米号 {user_id}。")

        try:
            notice_text = await fetch_server_notice_text()
        except Exception as e:  # noqa: BLE001
            logger.opt(exception=True).warning("管理员开服查询读取公告失败")
            if headless_status.connected:
                await broadcast_opened(event, now=now)
            lines.extend(
                (
                    "",
                    _build_fetch_failed_reply(now, e, headless_status=headless_status),
                )
            )
        else:
            lines.append("")
            if headless_status.connected:
                await broadcast_opened(event, now=now)
                lines.append(_build_open_reply(now, notice_text=notice_text))
            elif notice_text:
                lines.append(_build_notice_reply(notice_text))
            else:
                lines.append(
                    _build_no_notice_reply(now, headless_status=headless_status)
                )

        await finish_event_reply(
            matcher,
            event,
            "\n".join(lines),
            mention_sender=True,
        )

    async def _handle_restart(self, matcher: Any, event: MessageEvent) -> None:
        await handle_restart_command(matcher, event)


__all__ = ["ServerStatusPlugin"]
