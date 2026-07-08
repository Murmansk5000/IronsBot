# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent  # noqa: TC002
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata, on_fullmatch

from ironsbot.plugins.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.plugins.headless_seer_notice.service import login_headless_client
from ironsbot.plugins.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.shared.features import (
    groups_for_feature,
    is_event_feature_allowed,
    is_superuser,
    users_for_feature,
    users_with_superusers,
)
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    finish_event_reply,
    send_broadcast_message,
    send_event_reply,
)
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.shared.promotions import append_fire_manual_ad_for_group
from ironsbot.utils.rule import no_reply

from .config import (
    Config,
    get_docker_update_config,
    get_server_status_config,
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
    DEFAULT_START_TIME,
    DEFAULT_UPDATE_WEEKDAY,
    _build_fetch_failed_reply,
    _build_no_notice_reply,
    _build_notice_reply,
    _build_open_reply,
    _now,
    fetch_server_notice_text,
)
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
PARENT_EXIT_WAIT_SECONDS = 5.0
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


@dataclass(slots=True)
class OpenBroadcastState:
    last_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class HeadlessStatus:
    connected: bool
    reason: str = ""


_open_broadcast_state = OpenBroadcastState()


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
                await _broadcast_opened(event, now=now)
            await finish_event_reply(
                matcher,
                event,
                _build_fetch_failed_reply(now, e, headless_status=headless_status),
                mention_sender=True,
            )
            return

        if headless_status.connected:
            await _broadcast_opened(event, now=now)
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
                await _broadcast_opened(event, now=now)
            lines.extend(
                (
                    "",
                    _build_fetch_failed_reply(now, e, headless_status=headless_status),
                )
            )
        else:
            lines.append("")
            if headless_status.connected:
                await _broadcast_opened(event, now=now)
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
                await _restart_bot_process()
        elif restart_action == "process":
            await asyncio.sleep(BOT_RESTART_DELAY_SECONDS)
            await _restart_bot_process()


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


async def _broadcast_opened(event: MessageEvent, *, now: datetime) -> None:
    config = get_server_status_config()
    if not config.broadcast:
        logger.info("server status open broadcast skipped: disabled")
        return

    if not _should_broadcast_opened(now):
        return

    group_ids = groups_for_feature("server_status_push")
    user_ids = users_with_superusers(users_for_feature("server_status_push"))
    if not group_ids and not user_ids:
        logger.info("server status open broadcast skipped: no targets")
        return

    if not _can_trigger_open_broadcast(event, group_ids=group_ids, user_ids=user_ids):
        logger.info("server status open broadcast skipped: trigger not allowed")
        return

    if _is_open_broadcast_in_cooldown(now):
        logger.info("server status open broadcast skipped: cooldown")
        return

    summary = await send_broadcast_message(
        config.broadcast_message,
        group_ids=group_ids,
        private_user_ids=user_ids,
        action_name="server status open broadcast",
        interval_seconds=1.2,
        message_limiter=append_fire_manual_ad_for_group,
        subscription_key="server_status_push",
    )
    if summary.succeeded:
        _open_broadcast_state.last_at = now


def _should_broadcast_opened(now: datetime) -> bool:
    return (
        now.weekday() == DEFAULT_UPDATE_WEEKDAY
        and now.time() >= DEFAULT_START_TIME
    )


def _can_trigger_open_broadcast(
    event: MessageEvent,
    *,
    group_ids: list[int],
    user_ids: list[int],
) -> bool:
    if is_superuser(event.user_id):
        return True

    group_id = getattr(event, "group_id", None)
    if group_id is not None:
        return int(group_id) in group_ids

    return event.user_id in user_ids


def _is_open_broadcast_in_cooldown(now: datetime) -> bool:
    if _open_broadcast_state.last_at is None:
        return False

    cooldown_minutes = get_server_status_config().broadcast_cooldown_minutes
    if cooldown_minutes <= 0:
        return False

    return now - _open_broadcast_state.last_at < timedelta(minutes=cooldown_minutes)


def _get_headless_status() -> HeadlessStatus:
    try:
        from ironsbot.plugins.headless_seer.manager import client_manager

        game = client_manager.get_client()
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


async def _restart_bot_process() -> None:
    current_pid = os.getpid()
    parent_pid = os.getppid()
    target_pid = parent_pid if parent_pid > 0 else current_pid
    logger.warning(
        "admin requested bot restart: current_pid={}, target_pid={}",
        current_pid,
        target_pid,
    )
    os.kill(target_pid, signal.SIGTERM)
    if target_pid != current_pid:
        await asyncio.sleep(PARENT_EXIT_WAIT_SECONDS)
        logger.warning(
            "bot restart parent did not stop current worker yet; "
            "sending SIGTERM to current_pid={}",
            current_pid,
        )
        os.kill(current_pid, signal.SIGTERM)


_format_docker_image_created = format_docker_image_created
_split_docker_image = split_docker_image
_create_watchtower_container = create_watchtower_container
