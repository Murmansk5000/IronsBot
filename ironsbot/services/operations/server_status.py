# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import TYPE_CHECKING, Protocol
from zoneinfo import ZoneInfo

from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.services.operations.headless_pool import HeadlessRequestPriority
from ironsbot.services.seer.external_references import (
    SeerInfoReference,
    SeerInfoReferences,
)

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.operations.headless_session import HeadlessSessionFactory

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_UPDATE_WEEKDAY = 4
DEFAULT_START_TIME = time(hour=10)
DEFAULT_END_TIME = time(hour=15)
MAINTENANCE_RANGE_PATTERN = re.compile(
    r"(?:(?P<year>\d{4})\s*年\s*)?"
    r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日"
    r".{0,40}?"
    r"(?P<start_hour>\d{1,2})\s*(?:[:：]\s*(?P<start_minute>\d{1,2})|点(?P<start_minute_cn>\d{1,2})?分?)"
    r"\s*(?:-|~|\u2014|\u2013|至|到|－)\s*"
    r"(?:(?P<end_month>\d{1,2})\s*月\s*(?P<end_day>\d{1,2})\s*日.{0,20}?)?"
    r"(?P<end_hour>\d{1,2})\s*(?:[:：]\s*(?P<end_minute>\d{1,2})|点(?P<end_minute_cn>\d{1,2})?分?)"
)
logger = logging.getLogger(__name__)


class ServerNoticeSource(Protocol):
    async def fetch(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ServerStatusResult:
    message: str


@dataclass(frozen=True, slots=True)
class _HeadlessStatus:
    connected: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class _MaintenanceWindow:
    start: datetime
    end: datetime


class ServerStatusService:
    def __init__(
        self,
        headless: HeadlessService,
        notices: ServerNoticeSource,
        *,
        dedicated_sessions: HeadlessSessionFactory | None = None,
        external_references: SeerInfoReferences | None = None,
    ) -> None:
        self._headless = headless
        self._notices = notices
        self._dedicated_sessions = dedicated_sessions
        self._external_references = external_references

    async def query_headless_instances(self) -> ServerStatusResult:
        public_online = self._headless.healthy_worker_count
        public_configured = self._headless.configured_worker_count
        public_idle = self._headless.idle_worker_count
        dedicated_online = (
            self._dedicated_sessions.active_session_count
            if self._dedicated_sessions is not None
            else 0
        )
        lines = [
            "🛠【无头实例状态】",
            (
                "公共查询池："
                f"{public_online}/{public_configured} 在线，{public_idle} 空闲"
            ),
            f"临时专用会话：{dedicated_online} 在线",
            f"当前合计：{public_online + dedicated_online} 在线",
        ]
        pending = getattr(self._headless, "pending_request_counts", {})
        queued = _format_public_pool_queue(pending)
        if queued:
            lines.append(f"公共查询等待：{queued}")
        if self._dedicated_sessions is not None:
            labels = self._dedicated_sessions.active_sessions_by_label
            if labels:
                details = "、".join(
                    f"{label} {count}"
                    for label, count in sorted(labels.items())
                )
                lines.append(f"专用会话明细：{details}")
        lines.append("临时专用会话会在对应查询完成后立即下线。")
        return ServerStatusResult(message="\n".join(lines))
    async def query_normal(self) -> ServerStatusResult:
        now = datetime.now(LOCAL_TZ)
        status = self._headless_status()
        await self._record_status(status, source="开服了吗")
        return ServerStatusResult(message=self._with_reference(
            await self._notice_reply(status, now)
        ))

    async def query_admin(self) -> ServerStatusResult:
        now = datetime.now(LOCAL_TZ)
        status = self._headless_status()
        lines = ["🛠【管理员开服查询】"]
        if status.connected:
            await self._record_status(status, source="/开服查询")
            lines.append("无头状态：已登录游戏服务器。")
        else:
            await self._record_status(status, source="/开服查询")
            lines.append(f"无头状态：未登录（{status.reason}）。")
            try:
                user_id = await self._headless.login()
            except Exception as error:  # noqa: BLE001
                logger.warning("管理员开服查询触发无头重连失败", exc_info=True)
                status = _HeadlessStatus(connected=False, reason=str(error))
                await self._record_status(status, source="/开服查询重连")
                lines.append(f"重连结果：失败：{error}")
            else:
                status = _HeadlessStatus(connected=True)
                await self._headless.mark_available(
                    source="/开服查询重连",
                    user_id=user_id,
                )
                lines.append(f"重连结果：已登录米米号 {user_id}。")

        lines.extend(("", await self._notice_reply(status, now)))
        return ServerStatusResult(message=self._with_reference("\n".join(lines)))

    def _with_reference(self, message: str) -> str:
        if self._external_references is None:
            return message
        return self._external_references.append(
            message,
            SeerInfoReference.SERVER_STATUS,
        )

    def _headless_status(self) -> _HeadlessStatus:
        try:
            game = self._headless.get_game()
        except (DisconnectedError, NotLoggedInError) as error:
            return _HeadlessStatus(connected=False, reason=str(error))
        except Exception:  # noqa: BLE001
            logger.warning("开服查询检查无头客户端状态失败", exc_info=True)
            return _HeadlessStatus(
                connected=False,
                reason="检查机器人登录状态失败",
            )
        if bool(getattr(game, "is_logged_in", False)):
            return _HeadlessStatus(connected=True)
        return _HeadlessStatus(
            connected=False,
            reason="无头客户端未处于已登录状态",
        )

    async def _record_status(
        self,
        status: _HeadlessStatus,
        *,
        source: str,
    ) -> None:
        if status.connected:
            await self._headless.mark_available(source=source)
        else:
            await self._headless.mark_unavailable(status.reason, source=source)

    async def _notice_reply(
        self,
        status: _HeadlessStatus,
        now: datetime,
    ) -> str:
        try:
            notice_text = await self._notices.fetch()
        except Exception as error:  # noqa: BLE001
            logger.warning("开服公告读取失败", exc_info=True)
            return _build_fetch_failed_reply(status, error)
        if status.connected:
            return _build_open_reply(now, notice_text=notice_text)
        if notice_text:
            return notice_text
        return "可能还在维护、开服波动，或登录服/网络暂时不稳定。"


def _format_public_pool_queue(
    counts: dict[HeadlessRequestPriority, int],
) -> str:
    labels = (
        (HeadlessRequestPriority.SUPERUSER_BASIC, "超管基础"),
        (HeadlessRequestPriority.SUPERUSER_DETAIL, "超管详情"),
        (HeadlessRequestPriority.BASIC, "基础资料"),
        (HeadlessRequestPriority.INTERACTIVE, "主动详情"),
        (HeadlessRequestPriority.BACKGROUND, "后台预热"),
    )
    return "、".join(
        f"{label} {count}"
        for priority, label in labels
        if (count := counts.get(priority, 0))
    )


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
                f"公告读取失败：{type(notice_error).__name__}，但无头客户端已登录。",
            )
        )
    return "\n".join(lines)


def _build_fetch_failed_reply(
    status: _HeadlessStatus,
    error: Exception,
) -> str:
    if status.connected:
        return _build_open_reply(
            datetime.now(LOCAL_TZ),
            notice_error=error,
        )
    reason = status.reason.strip() or "状态未知"
    return (
        f"公告读取失败（{type(error).__name__}），"
        "机器人也没有登录游戏服务器，暂时不能确认已开服。\n"
        f"机器人登录状态：{reason}。\n"
        "可能还在维护、开服波动，或登录服/网络暂时不稳定。"
    )


def _build_notice_summary(notice_text: str, now: datetime) -> str:
    window = _parse_maintenance_window(notice_text, now)
    if window is None:
        return f"检测到维护公告：{_short_notice_text(notice_text)}"
    if now < window.start:
        status = "还没到公告维护时间"
    elif now <= window.end:
        status = f"维护中，预计 {window.end:%m-%d %H:%M} 开服"
    else:
        status = "公告仍在，但已超过公告结束时间，可能延迟开服"
    return (
        f"公告摘要：{status}\n"
        f"公告时间：{window.start:%m-%d %H:%M} ~ {window.end:%m-%d %H:%M}\n"
        f"公告内容：{_short_notice_text(notice_text)}"
    )


def _parse_maintenance_window(
    text: str,
    now: datetime,
) -> _MaintenanceWindow | None:
    match = MAINTENANCE_RANGE_PATTERN.search(text)
    if match is None:
        return None
    year = _int_group(match, "year", now.year)
    month = _int_group(match, "month", now.month)
    day = _int_group(match, "day", now.day)
    start = _safe_datetime(
        year,
        month,
        day,
        _int_group(match, "start_hour", DEFAULT_START_TIME.hour),
        _minute_group(match, "start_minute", "start_minute_cn"),
    )
    end = _safe_datetime(
        year,
        _int_group(match, "end_month", month),
        _int_group(match, "end_day", day),
        _int_group(match, "end_hour", DEFAULT_END_TIME.hour),
        _minute_group(match, "end_minute", "end_minute_cn"),
    )
    return None if start is None or end is None else _MaintenanceWindow(start, end)


def _safe_datetime(
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
    return default if not value else int(value)


def _minute_group(
    match: re.Match[str],
    colon_name: str,
    chinese_name: str,
) -> int:
    return _int_group(match, colon_name, _int_group(match, chinese_name, 0))


def _short_notice_text(text: str, *, max_chars: int = 120) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = " ".join(lines) if lines else text.strip()
    return summary if len(summary) <= max_chars else f"{summary[:max_chars]}..."
