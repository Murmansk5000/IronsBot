import asyncio
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from nonebot.log import logger

from ironsbot.custom_plugins.message_actions import send_broadcast_message
from ironsbot.shared.features import get_superuser_ids

from .config import get_headless_notice_config
from .service import headless_user_id_text

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DAILY_QUIET_START = time(hour=23, minute=55)
DAILY_QUIET_END = time(hour=0, minute=5)
FRIDAY_UPDATE_WEEKDAY = 4
FRIDAY_QUIET_START = time(hour=9, minute=50)
FRIDAY_QUIET_END = time(hour=15, minute=0)


@dataclass(slots=True)
class HeadlessState:
    connected: bool | None = None


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


async def _record_headless_state(
    *,
    connected: bool,
    reason: str,
    source: str,
    user_id: int | None,
    notify: bool,
) -> None:
    async with _state_lock:
        previous = _state.connected
        if previous == connected:
            return

        _state.connected = connected

    if previous is None or not notify:
        return

    if in_headless_notice_quiet_window():
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
    )


async def _send_headless_state_notice(
    *,
    connected: bool,
    reason: str,
    source: str,
    user_id: int | None,
) -> None:
    target_users = sorted(get_superuser_ids())
    if not target_users:
        logger.warning("headless state notice has no superusers")
        return

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
    )
    await send_broadcast_message(
        message,
        private_user_ids=target_users,
        action_name="headless state notice",
        interval_seconds=1.2,
    )
