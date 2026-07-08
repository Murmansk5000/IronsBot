# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent  # noqa: TC002
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata, on_fullmatch

from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.plugins.headless_seer_notice.service import login_headless_client
from ironsbot.plugins.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.services.seer.client import get_game_client
from ironsbot.shared.features import (
    is_event_feature_allowed,
)
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    finish_event_reply,
    send_event_reply,
)
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from .broadcast import broadcast_opened
from .config import (
    Config,
    get_docker_update_config,
)
from .docker_update import (
    DockerUpdateResult,
    WatchtowerUpdateOptions,
    create_watchtower_container,
    format_docker_image_created,
    split_docker_image,
)
from .docker_update import (
    format_docker_update_reply as _format_docker_update_reply,
)
from .docker_update import (
    is_docker_update_started as _is_docker_update_started,
)
from .docker_update import (
    resolve_docker_container_name as _resolve_docker_container_name,
)
from .docker_update import (
    restart_docker_container as _restart_docker_container,
)
from .notice import (
    _build_fetch_failed_reply,
    _build_no_notice_reply,
    _build_notice_reply,
    _build_open_reply,
    _now,
    fetch_server_notice_text,
)
from .process_restart import restart_bot_process
from .restart import DockerSelfUpdateService, RestartService

__all__ = [
    "DockerSelfUpdateService",
    "DockerUpdateResult",
    "RestartService",
    "WatchtowerUpdateOptions",
    "_create_watchtower_container",
    "_format_docker_image_created",
    "_format_docker_update_reply",
    "_is_docker_update_started",
    "_resolve_docker_container_name",
    "_split_docker_image",
]

NORMAL_SERVER_STATUS_COMMAND = "开服了吗"
DISABLED_BARE_ADMIN_COMMAND = "开服查询"
ADMIN_SERVER_STATUS_COMMAND = "/开服查询"
BOT_RESTART_COMMANDS = ("/机器人重启", "/重启机器人")
DOCKER_UPDATE_COMMANDS = ("/更新镜像", "/更新Docker", "/更新docker")
SERVER_STATUS_PLUGIN_NAME = "server_status"
BOT_RESTART_DELAY_SECONDS = 1.0
RESTART_CONTAINER_STOP_TIMEOUT_SECONDS = 3

__plugin_meta__ = PluginMetadata(
    name="开服查询",
    description="查询赛尔号维护公告，并结合无头客户端连接状态判断是否已开服",
    usage="""命令：
  开服了吗 — 普通用户查询当前是否仍有维护公告
  /开服查询 — 超级管理员查询，并在无头未登录时尝试重连
  /机器人重启 / /重启机器人 — 超级管理员重启机器人进程
  /更新镜像 / /更新Docker — 同义命令，进入同一套重启流程；
    是否检查镜像由 runtime.docker_update.check_on_restart 控制

说明：
  裸的“开服查询”已停用，避免和管理员命令混淆。
  无头客户端已登录游戏服务器时判定为已开服；公告只作为维护信息摘要。
  无头客户端未登录时，结合公告和登录状态提示可能原因。
  如果 runtime.server_status.broadcast=true，查询结果判断为已开服时会向
  Broadcast targets use FEATURE_GROUP_POLICY / FEATURE_USER_POLICY
  feature: server_status_push.
  配置的目标广播。""",
    config=Config,
    supported_adapters={"~onebot.v11"},
)


@dataclass(frozen=True, slots=True)
class HeadlessStatus:
    connected: bool
    reason: str = ""


normal_server_status_matcher = on_fullmatch(
    NORMAL_SERVER_STATUS_COMMAND,
    rule=no_reply(),
    priority=get_matcher_priority("server_status", 0),
    block=True,
)
disabled_bare_admin_status_matcher = on_fullmatch(
    DISABLED_BARE_ADMIN_COMMAND,
    rule=no_reply(),
    priority=get_matcher_priority("server_status", 0),
    block=True,
)
admin_server_status_matcher = on_fullmatch(
    ADMIN_SERVER_STATUS_COMMAND,
    rule=no_reply(),
    permission=SUPERUSER,
    priority=get_matcher_priority("server_status_admin", 1),
    block=True,
)
bot_restart_matcher = on_fullmatch(
    BOT_RESTART_COMMANDS,
    rule=no_reply(),
    permission=SUPERUSER,
    priority=get_matcher_priority("server_status_admin", 1),
    block=True,
)
docker_update_matcher = on_fullmatch(
    DOCKER_UPDATE_COMMANDS,
    rule=no_reply(),
    permission=SUPERUSER,
    priority=get_matcher_priority("server_status_admin", 1),
    block=True,
)


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
        config = get_docker_update_config()
        restart_service = RestartService(config)
        message, restart_action = await restart_service.prepare_manual_restart()
        await send_event_reply(
            matcher,
            event,
            message,
            mention_sender=True,
        )
        if restart_action == "docker":
            await asyncio.sleep(BOT_RESTART_DELAY_SECONDS)
            try:
                await _restart_docker_container(
                    container_name=_resolve_docker_container_name(
                        str(config.container_name)
                    ),
                    socket_path=str(config.docker_socket_path),
                    timeout_seconds=float(config.timeout_seconds),
                )
            except Exception:  # noqa: BLE001
                logger.opt(exception=True).warning(
                    "docker container restart failed; falling back to process restart"
                )
                await restart_bot_process()
        elif restart_action == "process":
            await asyncio.sleep(BOT_RESTART_DELAY_SECONDS)
            await restart_bot_process()


register_plugin(ServerStatusPlugin())


@normal_server_status_matcher.handle()
async def handle_normal_server_status(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=SERVER_STATUS_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="normal",
    )


@disabled_bare_admin_status_matcher.handle()
async def handle_disabled_bare_admin_status(event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=SERVER_STATUS_PLUGIN_NAME,
        event=event,
        matcher=disabled_bare_admin_status_matcher,
        action="disabled_bare_admin",
    )


@admin_server_status_matcher.handle()
async def handle_admin_server_status(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=SERVER_STATUS_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="admin",
    )


@bot_restart_matcher.handle()
async def handle_bot_restart(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=SERVER_STATUS_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="restart",
    )


@docker_update_matcher.handle()
async def handle_docker_update(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=SERVER_STATUS_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        action="docker_update",
    )


def _get_headless_status() -> HeadlessStatus:
    try:
        game = get_game_client()
    except (DisconnectedError, NotLoggedInError) as e:
        return HeadlessStatus(connected=False, reason=str(e))
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("开服查询检查无头客户端状态失败")
        return HeadlessStatus(
            connected=False,
            reason="检查机器人登录状态失败",
        )

    if bool(getattr(game, "is_logged_in", False)):
        return HeadlessStatus(connected=True)

    return HeadlessStatus(
        connected=False,
        reason="无头客户端未处于已登录状态",
    )


def _format_headless_unavailable_text(reason: str) -> str:
    reason = reason.strip() or "状态未知"
    return f"机器人登录状态：{reason}。"


_format_docker_image_created = format_docker_image_created
_split_docker_image = split_docker_image
_create_watchtower_container = create_watchtower_container
