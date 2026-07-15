import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from nonebot.log import logger

from ironsbot.shared.messaging.admin_notice import send_admin_notice

from .config import get_headless_notice_config

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DAILY_QUIET_START = time(hour=23, minute=55)
DAILY_QUIET_END = time(hour=0, minute=5)
FRIDAY_UPDATE_WEEKDAY = 4
FRIDAY_QUIET_START = time(hour=9, minute=50)
FRIDAY_QUIET_END = time(hour=15, minute=0)
MAX_DURATION_PARTS = 2


@dataclass(slots=True)
class HeadlessState:
    connected: bool | None = None
    offline_since: datetime | None = None


_state = HeadlessState()
_state_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _in_daily_quiet_window(current_time: time) -> bool:
    return current_time >= DAILY_QUIET_START or current_time <= DAILY_QUIET_END


def _in_friday_update_quiet_window(now: datetime) -> bool:
    return (
        now.weekday() == FRIDAY_UPDATE_WEEKDAY
        and FRIDAY_QUIET_START <= now.time() <= FRIDAY_QUIET_END
    )


def in_headless_notice_quiet_window(now: datetime | None = None) -> bool:
    now = now or _now()
    return _in_daily_quiet_window(now.time()) or _in_friday_update_quiet_window(now)


async def mark_headless_available(
    *,
    source: str,
    user_id: int | None = None,
    notify: bool = True,
) -> None:
    await _record_headless_state(
        connected=True,
        reason="",
        source=source,
        user_id=user_id,
        notify=notify,
    )


async def mark_headless_unavailable(
    reason: str,
    *,
    source: str,
    notify: bool = True,
) -> None:
    await _record_headless_state(
        connected=False,
        reason=reason,
        source=source,
        user_id=None,
        notify=notify,
    )


async def mark_headless_game_state(
    *,
    connected: bool,
    reason: str,
    source: str,
    user_id: int | None,
) -> None:
    await _record_headless_state(
        connected=connected,
        reason=reason,
        source=source,
        user_id=user_id,
        notify=True,
    )


async def _record_headless_state(
    *,
    connected: bool,
    reason: str,
    source: str,
    user_id: int | None,
    notify: bool,
) -> None:
    now = _now()
    async with _state_lock:
        previous = _state.connected
        if previous == connected:
            return

        offline_since = _state.offline_since
        _state.connected = connected
        if connected:
            _state.offline_since = None
        else:
            _state.offline_since = now

    if previous is None or not notify:
        return

    if in_headless_notice_quiet_window(now):
        logger.info(
            "headless state notice suppressed by quiet window: {} -> {} ({})",
            previous,
            connected,
            source,
        )
        return

    notice_config = get_headless_notice_config()
    if not notice_config.state_notice:
        logger.info("headless state notice disabled")
        return

    await _send_headless_state_notice(
        connected=connected,
        reason=reason,
        source=source,
        user_id=user_id,
        offline_duration=_format_offline_duration(
            now - offline_since if connected and offline_since is not None else None
        ),
    )


async def _send_headless_state_notice(
    *,
    connected: bool,
    reason: str,
    source: str,
    user_id: int | None,
    offline_duration: str = "",
) -> None:
    from .service import headless_user_id_text

    notice_config = get_headless_notice_config()
    message_template = (
        notice_config.state_online_message
        if connected
        else notice_config.state_offline_message
    )
    message = message_template.format(
        user_id=user_id or headless_user_id_text(),
        reason=reason.strip() or "状态未知",
        source=source.strip() or "状态检测",
        offline_duration=offline_duration or "未知",
    )
    await send_admin_notice(
        message,
        action_name="headless state notice",
        interval_seconds=1.2,
        subscription_key="headless_seer_notice",
    )


def _format_offline_duration(delta: timedelta | None) -> str:
    if delta is None:
        return "未知"

    total_seconds = max(0, int(delta.total_seconds()))
    days, remainder = divmod(total_seconds, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes and len(parts) < MAX_DURATION_PARTS:
        parts.append(f"{minutes}分钟")
    if not parts or (not days and not hours):
        parts.append(f"{seconds}秒")
    return "".join(parts)
