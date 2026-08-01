# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from logging import getLogger
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.config.models.operations import HeadlessConfig, HeadlessNoticeConfig
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.operations.headless_activity import (
        HeadlessOperationTracker,
    )

logger = getLogger(__name__)

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DAILY_QUIET_START = time(hour=23, minute=55)
DAILY_QUIET_END = time(hour=0, minute=5)
FRIDAY_UPDATE_WEEKDAY = 4
FRIDAY_QUIET_START = time(hour=9, minute=50)
FRIDAY_QUIET_END = time(hour=15, minute=0)
MAX_DURATION_PARTS = 2
HEADLESS_CONFIG_MISSING_MESSAGE = "未配置无头米米号或密码"


class HeadlessStateNotifier(Protocol):
    async def __call__(
        self,
        *,
        connected: bool,
        reason: str,
        source: str,
        user_id: int | None,
    ) -> None: ...


class HeadlessStateListener(Protocol):
    async def __call__(
        self,
        *,
        previous: bool | None,
        connected: bool,
        reason: str,
        source: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class HeadlessLoginRequest:
    user_id: int
    password: str
    login_server_url: str
    heartbeat_interval: float | None
    request_timeout_seconds: float
    reconnect_retries: int
    reconnect_delay: float
    reconnect_delay_max: float
    state_notifier: HeadlessStateNotifier
    request_interval_seconds: float = 0.0


class HeadlessGame(Protocol):
    @property
    def is_logged_in(self) -> bool: ...

    @property
    def user_id(self) -> int: ...

    @property
    def operations(self) -> HeadlessOperationTracker: ...

    async def get_user_info(self, user_id: int) -> Any: ...

    async def get_more_user_info(self, user_id: int) -> Any: ...

    async def get_user_online_info(self, user_id: int) -> Any: ...

    async def get_team_info(self, team_id: int) -> Any: ...


class HeadlessClient(Protocol):
    def get_client(self) -> HeadlessGame: ...

    async def login(self, request: HeadlessLoginRequest) -> HeadlessGame: ...

    def shutdown(self) -> None: ...


@dataclass(slots=True)
class HeadlessState:
    connected: bool | None = None
    offline_since: datetime | None = None


def in_headless_notice_quiet_window(now: datetime) -> bool:
    current_time = now.time()
    daily_quiet = (
        current_time >= DAILY_QUIET_START or current_time <= DAILY_QUIET_END
    )
    friday_quiet = (
        now.weekday() == FRIDAY_UPDATE_WEEKDAY
        and FRIDAY_QUIET_START <= current_time <= FRIDAY_QUIET_END
    )
    return daily_quiet or friday_quiet


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


class HeadlessService:
    def __init__(  # noqa: PLR0913 - composed runtime dependencies
        self,
        client: HeadlessClient,
        connection: HeadlessConfig,
        notices: HeadlessNoticeConfig,
        admin_notices: AdminNoticeService,
        *,
        request_interval_seconds: float = 0.0,
        state_notifications: bool = True,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._connection = connection
        self._notices = notices
        self._admin_notices = admin_notices
        self._request_interval_seconds = max(request_interval_seconds, 0.0)
        self._state_notifications = state_notifications
        self._now = now or (lambda: datetime.now(LOCAL_TZ))
        self._state = HeadlessState()
        self._state_lock = asyncio.Lock()
        self._available = asyncio.Event()
        self._state_listeners: list[HeadlessStateListener] = []

    @property
    def configured(self) -> bool:
        return (
            self._connection.user_id is not None
            and bool(self._connection.password)
        )

    @property
    def user_id_text(self) -> str:
        return str(self._connection.user_id or "未配置")

    @property
    def reconnect_times(self) -> list[str]:
        return self._notices.parsed_reconnect_check_times

    def login_failure_reason(self) -> str | None:
        try:
            self._client.get_client()
        except Exception as error:  # noqa: BLE001
            return str(error)
        return None

    def get_game(self) -> HeadlessGame:
        return self._client.get_client()

    def add_state_listener(self, listener: HeadlessStateListener) -> None:
        self._state_listeners.append(listener)

    async def wait_until_available(self, *, timeout: float) -> HeadlessGame:
        try:
            return self.get_game()
        except (DisconnectedError, NotLoggedInError):
            pass
        try:
            await asyncio.wait_for(self._available.wait(), timeout=timeout)
        except TimeoutError as error:
            raise RuntimeError from error
        return self.get_game()

    async def login(self) -> int:
        try:
            game = self._client.get_client()
            if game.is_logged_in:
                return int(game.user_id)
        except (DisconnectedError, NotLoggedInError):
            pass

        user_id = self._connection.user_id
        password = self._connection.password
        if user_id is None or not password:
            raise RuntimeError(HEADLESS_CONFIG_MISSING_MESSAGE)

        game = await self._client.login(
            HeadlessLoginRequest(
                user_id=user_id,
                password=password,
                login_server_url=self._connection.login_server_addr,
                heartbeat_interval=self._connection.heartbeat_interval,
                request_timeout_seconds=self._connection.request_timeout_seconds,
                reconnect_retries=self._connection.reconnect_retries,
                reconnect_delay=self._connection.reconnect_delay,
                reconnect_delay_max=self._connection.reconnect_delay_max,
                state_notifier=self.mark_game_state,
                request_interval_seconds=self._request_interval_seconds,
            )
        )
        if not game.is_logged_in:
            raise RuntimeError("登录未完成，已进入自动重连")
        return user_id

    async def start(self) -> None:
        if not self.configured:
            logger.warning("无头客户端未配置米米号或密码，跳过登录")
            return
        try:
            await self.login()
        except Exception:
            logger.exception("无头客户端登录失败")

    async def shutdown(self) -> None:
        self._client.shutdown()

    async def check_on_connect(self) -> None:
        if not self.configured:
            return

        reason = self.login_failure_reason()
        if reason is None:
            await self.mark_available(source="启动检查", notify=False)
            return

        await self.mark_unavailable(reason, source="启动检查", notify=False)
        if self._state_notifications and self._notices.login_notice:
            await self._admin_notices.send(
                self._notices.login_notice_message.format(
                    user_id=self.user_id_text,
                    reason=reason,
                ),
                action_name="headless seer failure notice",
                interval_seconds=1.2,
                subscription_key="headless_seer_notice",
            )

    async def reconnect(self, scheduled_time: str) -> None:
        if not self.configured:
            logger.info("headless reconnect check skipped: not configured")
            return

        reason = self.login_failure_reason()
        if reason is None:
            await self.mark_available(
                source=f"定时检测 {scheduled_time}",
                notify=False,
            )
            return

        await self.mark_unavailable(
            reason,
            source=f"定时检测 {scheduled_time}",
        )
        try:
            user_id = await self.login()
        except Exception as error:
            logger.exception(
                "headless reconnect check failed at %s",
                scheduled_time,
            )
            await self.mark_unavailable(
                str(error),
                source=f"定时重连 {scheduled_time}",
            )
            return

        await self.mark_available(
            source=f"定时重连 {scheduled_time}",
            user_id=user_id,
        )

    async def mark_available(
        self,
        *,
        source: str,
        user_id: int | None = None,
        notify: bool = True,
    ) -> None:
        await self._record_state(
            connected=True,
            reason="",
            source=source,
            user_id=user_id,
            notify=notify,
        )

    async def mark_unavailable(
        self,
        reason: str,
        *,
        source: str,
        notify: bool = True,
    ) -> None:
        await self._record_state(
            connected=False,
            reason=reason,
            source=source,
            user_id=None,
            notify=notify,
        )

    async def mark_game_state(
        self,
        *,
        connected: bool,
        reason: str,
        source: str,
        user_id: int | None,
    ) -> None:
        await self._record_state(
            connected=connected,
            reason=reason,
            source=source,
            user_id=user_id,
            notify=True,
        )

    async def _record_state(
        self,
        *,
        connected: bool,
        reason: str,
        source: str,
        user_id: int | None,
        notify: bool,
    ) -> None:
        now = self._now()
        async with self._state_lock:
            previous = self._state.connected
            if previous == connected:
                return

            offline_since = self._state.offline_since
            self._state.connected = connected
            self._state.offline_since = None if connected else now
            if connected:
                self._available.set()
            else:
                self._available.clear()

        await self._notify_state_listeners(
            previous=previous,
            connected=connected,
            reason=reason,
            source=source,
        )

        if previous is None or not notify or not self._state_notifications:
            return
        if in_headless_notice_quiet_window(now):
            logger.info(
                "headless state notice suppressed by quiet window: %s -> %s (%s)",
                previous,
                connected,
                source,
            )
            return
        if not self._notices.state_notice:
            logger.info("headless state notice disabled")
            return

        message_template = (
            self._notices.state_online_message
            if connected
            else self._notices.state_offline_message
        )
        await self._admin_notices.send(
            message_template.format(
                user_id=user_id or self.user_id_text,
                reason=reason.strip() or "状态未知",
                source=source.strip() or "状态检测",
                offline_duration=_format_offline_duration(
                    now - offline_since
                    if connected and offline_since is not None
                    else None
                ),
            ),
            action_name="headless state notice",
            interval_seconds=1.2,
            subscription_key="headless_seer_notice",
        )

    async def _notify_state_listeners(
        self,
        *,
        previous: bool | None,
        connected: bool,
        reason: str,
        source: str,
    ) -> None:
        if not self._state_listeners:
            return
        try:
            await asyncio.gather(
                *(
                    listener(
                        previous=previous,
                        connected=connected,
                        reason=reason,
                        source=source,
                    )
                    for listener in tuple(self._state_listeners)
                )
            )
        except Exception:
            logger.exception("headless state listener failed")
