# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import os
import re
import signal
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from anyio import Path as AsyncPath
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

from .config import Config, get_docker_update_config, get_server_status_config

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
NOTICE_URL = "https://unity-notice.61.com/unity_notice/"
NORMAL_SERVER_STATUS_COMMAND = "开服了吗"
DISABLED_BARE_ADMIN_COMMAND = "开服查询"
ADMIN_SERVER_STATUS_COMMAND = "/开服查询"
BOT_RESTART_COMMANDS = ("/机器人重启", "/重启机器人")
DOCKER_UPDATE_COMMANDS = ("/更新镜像", "/更新Docker", "/更新docker")
SERVER_STATUS_PLUGIN_NAME = "server_status"
DEFAULT_UPDATE_WEEKDAY = 4
DEFAULT_START_TIME = time(hour=10)
DEFAULT_END_TIME = time(hour=15)
HTTP_TIMEOUT_SECONDS = 12.0
NOTICE_MAINTENANCE_TYPE = 3
BOT_RESTART_DELAY_SECONDS = 1.0
PARENT_EXIT_WAIT_SECONDS = 5.0

HTML_TAG_PATTERN = re.compile(r"<[^>]*>")
MAINTENANCE_RANGE_PATTERN = re.compile(
    r"(?:(?P<year>\d{4})\s*年\s*)?"
    r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日?"
    r".{0,40}?"
    r"(?P<start_hour>\d{1,2})\s*(?:[:：]\s*(?P<start_minute>\d{1,2})|点(?P<start_minute_cn>\d{1,2})?分?)"
    r"\s*(?:-|~|\u2014|\u2013|至|到|\uff0d)\s*"
    r"(?:(?P<end_month>\d{1,2})\s*月\s*(?P<end_day>\d{1,2})\s*日?.{0,20}?)?"
    r"(?P<end_hour>\d{1,2})\s*(?:[:：]\s*(?P<end_minute>\d{1,2})|点(?P<end_minute_cn>\d{1,2})?分?)"
)


__plugin_meta__ = PluginMetadata(
    name="开服查询",
    description="查询赛尔号维护公告，并结合无头客户端连接状态判断是否已开服",
    usage="""命令：
  开服了吗 — 普通用户查询当前是否仍有维护公告
  /开服查询 — 超级管理员查询，并在无头未登录时尝试重连
  /机器人重启 / /重启机器人 — 超级管理员重启机器人进程
  /更新镜像 / /更新Docker — 兼容别名，进入同一套重启流程；
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
class MaintenanceWindow:
    start: datetime
    end: datetime


@dataclass(slots=True)
class OpenBroadcastState:
    last_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class HeadlessStatus:
    connected: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class DockerUpdateResult:
    ok: bool
    message: str = ""
    updater_container_id: str = ""
    up_to_date: bool = False
    current_image_id: str = ""
    target_image_id: str = ""
    missing_socket: bool = False


_docker_update_lock = asyncio.Lock()
_open_broadcast_state = OpenBroadcastState()


class DockerSelfUpdateService:
    def __init__(self, config: object) -> None:
        self._config = config

    def resolve_container_name(self) -> str:
        return _resolve_docker_container_name(str(self._config.container_name))

    async def run(self) -> tuple[str, DockerUpdateResult]:
        container_name = self.resolve_container_name()
        async with _docker_update_lock:
            result = await _start_watchtower_update(
                container_name=container_name,
                image=str(self._config.image),
                socket_path=str(self._config.docker_socket_path),
                watchtower_image=str(self._config.watchtower_image),
                timeout_seconds=float(self._config.timeout_seconds),
            )
        return container_name, result


class RestartService:
    def __init__(self, config: object) -> None:
        self._config = config

    async def prepare_manual_restart(self) -> tuple[str, bool]:
        if not bool(self._config.check_on_restart):
            return (
                "正在重启机器人进程。\n"
                "当前配置未启用重启前镜像检查；如果运行在 Docker/Unraid，"
                "会按重启策略拉起同一镜像。",
                True,
            )

        container_name, result = await DockerSelfUpdateService(self._config).run()
        reply = _format_docker_update_reply(
            container_name=container_name,
            image=str(self._config.image),
            result=result,
        )
        if _is_docker_update_started(result):
            return reply, False

        if result.up_to_date:
            return f"{reply}\n\n镜像已是最新，继续普通重启。", True
        if result.missing_socket:
            return f"{reply}\n\n将跳过镜像检查并继续普通重启。", True
        return f"{reply}\n\n镜像检查失败，继续普通重启。", True

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

    async def _handle_normal(self, matcher: Matcher, event: MessageEvent) -> None:
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

    async def _handle_admin(self, matcher: Matcher, event: MessageEvent) -> None:
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

    async def _handle_restart(self, matcher: Matcher, event: MessageEvent) -> None:
        config = get_docker_update_config()
        restart_service = RestartService(config)
        message, should_restart = await restart_service.prepare_manual_restart()
        await send_event_reply(
            matcher,
            event,
            message,
            mention_sender=True,
        )
        if should_restart:
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


async def fetch_server_notice_text() -> str | None:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS),
    ) as client:
        response = await client.get(NOTICE_URL)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, list):
        return None

    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("type") == NOTICE_MAINTENANCE_TYPE:
            text = item.get("text")
            if isinstance(text, str):
                return _clean_notice_text(text)

    return None


def _build_open_reply(
    now: datetime,
    *,
    notice_text: str | None = None,
    notice_error: Exception | None = None,
) -> str:
    lines = ["开服了哦~（机器人已登录游戏服务器）"]
    if notice_text:
        lines.extend(("", _build_notice_summary(notice_text, now)))
    if notice_error is not None:
        lines.extend(
            (
                "",
                f"公告读取失败：{notice_error.__class__.__name__}，但无头客户端已登录。",
            )
        )
    return "\n".join(lines)


def _build_notice_reply(notice_text: str) -> str:
    return notice_text


def _build_notice_summary(notice_text: str, now: datetime) -> str:
    window = _parse_maintenance_window(notice_text, now)
    if window is None:
        return f"检测到维护公告：{_short_notice_text(notice_text)}"

    if now < window.start:
        status = "还没到公告维护时间"
    elif now <= window.end:
        status = f"维护中，预计 {_format_datetime(window.end)} 开服"
    else:
        status = "公告仍在，但已超过公告结束时间，可能延迟开服"

    return (
        f"公告摘要：{status}\n"
        "公告时间："
        f"{_format_datetime(window.start)} ~ {_format_datetime(window.end)}\n"
        f"公告内容：{_short_notice_text(notice_text)}"
    )


def _build_no_notice_reply(now: datetime, *, headless_status: HeadlessStatus) -> str:
    if headless_status.connected:
        return _build_open_reply(now)

    return "可能还在维护、开服波动，或登录服/网络暂时不稳定。"


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


def _build_fetch_failed_reply(
    now: datetime,
    error: Exception,
    *,
    headless_status: HeadlessStatus,
) -> str:
    error_name = error.__class__.__name__
    if headless_status.connected:
        return _build_open_reply(now, notice_error=error)

    reason_text = _format_headless_unavailable_text(headless_status.reason)
    return (
        f"公告读取失败（{error_name}），机器人也没有登录游戏服务器，暂时不能确认已开服。\n"
        f"{reason_text}\n"
        "可能还在维护、开服波动，或登录服/网络暂时不稳定。"
    )


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


async def _start_watchtower_update(
    *,
    container_name: str,
    image: str,
    socket_path: str,
    watchtower_image: str,
    timeout_seconds: float,
) -> DockerUpdateResult:
    logger.warning(
        "admin requested docker self update: container={}, watchtower={}",
        container_name,
        watchtower_image,
    )
    if not await AsyncPath(socket_path).exists():
        logger.warning("docker self update failed: socket not found: {}", socket_path)
        return DockerUpdateResult(
            ok=False,
            missing_socket=True,
            message=f"Docker socket not found: {socket_path}",
        )

    transport = httpx.AsyncHTTPTransport(uds=socket_path)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://docker",
            timeout=httpx.Timeout(timeout_seconds),
        ) as client:
            current_image_id = await _inspect_container_image_id(
                client,
                container_name,
            )
            target_image_id = await _pull_docker_image(client, image)
            if current_image_id == target_image_id:
                return DockerUpdateResult(
                    ok=True,
                    up_to_date=True,
                    current_image_id=current_image_id,
                    target_image_id=target_image_id,
                )

            await _pull_docker_image(client, watchtower_image)
            updater_id = await _create_watchtower_container(
                client,
                container_name=container_name,
                socket_path=socket_path,
                watchtower_image=watchtower_image,
            )
            response = await client.post(f"/containers/{updater_id}/start")
            response.raise_for_status()
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=True).warning("docker self update failed")
        return DockerUpdateResult(ok=False, message=str(e))

    return DockerUpdateResult(
        ok=True,
        updater_container_id=updater_id,
        current_image_id=current_image_id,
        target_image_id=target_image_id,
    )


async def _inspect_container_image_id(
    client: httpx.AsyncClient,
    container_name: str,
) -> str:
    response = await client.get(f"/containers/{quote(container_name, safe='')}/json")
    response.raise_for_status()
    data = response.json()
    image_id = data.get("Image")
    if not isinstance(image_id, str) or not image_id:
        msg = "Docker API did not return current container image id"
        raise RuntimeError(msg)
    return image_id


async def _pull_docker_image(
    client: httpx.AsyncClient,
    image: str,
) -> str:
    repository, tag = _split_docker_image(image)
    response = await client.post(
        "/images/create",
        params={"fromImage": repository, "tag": tag},
    )
    response.raise_for_status()
    return await _inspect_image_id(client, image)


async def _inspect_image_id(client: httpx.AsyncClient, image: str) -> str:
    response = await client.get(f"/images/{quote(image, safe='')}/json")
    response.raise_for_status()
    data = response.json()
    image_id = data.get("Id")
    if not isinstance(image_id, str) or not image_id:
        msg = "Docker API did not return target image id"
        raise RuntimeError(msg)
    return image_id


async def _create_watchtower_container(
    client: httpx.AsyncClient,
    *,
    container_name: str,
    socket_path: str,
    watchtower_image: str,
) -> str:
    updater_name = f"ironsbot-watchtower-once-{uuid4().hex[:12]}"
    response = await client.post(
        "/containers/create",
        params={"name": updater_name},
        json={
            "Image": watchtower_image,
            "Cmd": ["--run-once", "--cleanup", container_name],
            "HostConfig": {
                "AutoRemove": True,
                "Binds": [f"{socket_path}:/var/run/docker.sock"],
            },
        },
    )
    response.raise_for_status()
    data = response.json()
    container_id = data.get("Id")
    if not isinstance(container_id, str) or not container_id:
        msg = "Docker API did not return updater container id"
        raise RuntimeError(msg)
    return container_id


def _format_docker_update_reply(
    *,
    container_name: str,
    image: str,
    result: DockerUpdateResult,
) -> str:
    if result.missing_socket:
        return (
            "Docker 镜像检查已跳过：容器内没有找到 Docker socket。\n"
            "需要给 IronsBot 容器额外挂载：\n"
            "/var/run/docker.sock -> /var/run/docker.sock\n"
            "挂载后再发送 /重启机器人 或 /更新镜像。"
        )

    if result.up_to_date:
        return (
            f"Docker 镜像已是最新：{container_name}\n"
            f"目标镜像：{image}\n"
            f"镜像 ID：{_short_image_id(result.target_image_id)}"
        )

    if result.ok:
        return (
            f"检测到新镜像，Docker 自更新任务已启动：{container_name}\n"
            f"目标镜像：{image}\n"
            f"当前镜像：{_short_image_id(result.current_image_id)}\n"
            f"最新镜像：{_short_image_id(result.target_image_id)}\n"
            "接下来 Watchtower 会拉取最新镜像并重建当前容器，"
            "机器人可能会短暂离线；重启后才算真正使用新镜像。\n"
            f"更新任务容器：{result.updater_container_id[:12]}"
        )

    return (
        f"Docker 镜像检查失败：{container_name}\n"
        f"目标镜像：{image}\n"
        f"错误：{result.message or '未知错误'}"
    ).rstrip()


def _is_docker_update_started(result: DockerUpdateResult) -> bool:
    return bool(result.ok and not result.up_to_date and result.updater_container_id)


def _resolve_docker_container_name(configured_name: str) -> str:
    return os.getenv("HOST_CONTAINERNAME", "").strip() or configured_name


def _split_docker_image(image: str) -> tuple[str, str]:
    last_segment = image.rsplit("/", maxsplit=1)[-1]
    if ":" not in last_segment:
        return image, "latest"
    repository, tag = image.rsplit(":", maxsplit=1)
    return repository, tag


def _short_image_id(image_id: str) -> str:
    if not image_id:
        return "未知"
    return image_id.removeprefix("sha256:")[:12]


def _short_notice_text(text: str, *, max_chars: int = 120) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = " ".join(lines) if lines else text.strip()
    if len(summary) <= max_chars:
        return summary
    return f"{summary[:max_chars]}..."


def _parse_maintenance_window(text: str, now: datetime) -> MaintenanceWindow | None:
    match = MAINTENANCE_RANGE_PATTERN.search(text)
    if match is None:
        return None

    year = _int_group(match, "year", now.year)
    month = _int_group(match, "month", now.month)
    day = _int_group(match, "day", now.day)
    end_month = _int_group(match, "end_month", month)
    end_day = _int_group(match, "end_day", day)

    start = _safe_datetime(
        year=year,
        month=month,
        day=day,
        hour=_int_group(match, "start_hour", DEFAULT_START_TIME.hour),
        minute=_minute_group(match, "start_minute", "start_minute_cn"),
    )
    end = _safe_datetime(
        year=year,
        month=end_month,
        day=end_day,
        hour=_int_group(match, "end_hour", DEFAULT_END_TIME.hour),
        minute=_minute_group(match, "end_minute", "end_minute_cn"),
    )
    if start is None or end is None:
        return None

    return MaintenanceWindow(start=start, end=end)


def _safe_datetime(
    *,
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
) -> datetime | None:
    try:
        return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ)
    except ValueError:
        return None


def _int_group(match: re.Match[str], name: str, default: int) -> int:
    value = match.group(name)
    if value is None or value == "":
        return default
    return int(value)


def _minute_group(
    match: re.Match[str],
    colon_name: str,
    chinese_name: str,
) -> int:
    return _int_group(match, colon_name, _int_group(match, chinese_name, 0))


def _is_default_update_window(now: datetime) -> bool:
    return (
        now.weekday() == DEFAULT_UPDATE_WEEKDAY
        and DEFAULT_START_TIME <= now.time() < DEFAULT_END_TIME
    )


def _clean_notice_text(text: str) -> str:
    cleaned = HTML_TAG_PATTERN.sub("", text)
    return cleaned.replace("\\n", "\n").strip()


def _format_datetime(value: datetime) -> str:
    return value.strftime("%m-%d %H:%M")


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)
