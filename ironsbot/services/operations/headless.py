# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from logging import getLogger
from typing import TYPE_CHECKING, Any, Protocol, cast
from zoneinfo import ZoneInfo

from ironsbot.services.operations.headless_activity import HeadlessOperationTracker
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.services.operations.headless_pool import (
    HeadlessRequestDispatcher,
    HeadlessWorkerSlot,
    PooledHeadlessGame,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.config.models.operations import HeadlessConfig, HeadlessNoticeConfig
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.messaging.admin_notice import AdminNoticeService

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

    async def send_and_wait(
        self,
        command_id: Any,
        *body: object,
        timeout: float | None = None,
    ) -> Any: ...


class HeadlessClient(Protocol):
    def get_client(self) -> HeadlessGame: ...

    async def login(self, request: HeadlessLoginRequest) -> HeadlessGame: ...

    def shutdown(self) -> None: ...


@dataclass(slots=True)
class HeadlessState:
    connected: bool | None = None
    offline_since: datetime | None = None


@dataclass(slots=True)
class _HeadlessWorkerRuntime:
    name: str
    user_id: int
    password: str
    client: HeadlessClient
    state: HeadlessState


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
        client: HeadlessClient | Sequence[HeadlessClient],
        connection: HeadlessConfig,
        notices: HeadlessNoticeConfig,
        admin_notices: AdminNoticeService,
        *,
        request_interval_seconds: float = 0.0,
        state_notifications: bool = True,
        now: Callable[[], datetime] | None = None,
        spawn: TaskSpawner | None = None,
    ) -> None:
        self._connection = connection
        self._notices = notices
        self._admin_notices = admin_notices
        self._request_interval_seconds = max(request_interval_seconds, 0.0)
        self._state_notifications = state_notifications
        self._now = now or (lambda: datetime.now(LOCAL_TZ))
        clients = (
            list(client)
            if isinstance(client, Sequence)
            else [client]
        )
        credentials: list[tuple[str, int, str]] = []
        if connection.user_id is not None and connection.password:
            credentials.append(
                ("primary", int(connection.user_id), str(connection.password))
            )
        credentials.extend(
            (worker.name, int(worker.user_id), str(worker.password))
            for worker in connection.workers
            if worker.user_id is not None and worker.password
        )
        if len(clients) < max(1, len(credentials)):
            message = "not enough headless clients for configured workers"
            raise ValueError(message)
        self._workers = [
            _HeadlessWorkerRuntime(
                name=name,
                user_id=user_id,
                password=password,
                client=clients[index],
                state=HeadlessState(),
            )
            for index, (name, user_id, password) in enumerate(credentials)
        ]
        self._state = HeadlessState()
        self._state_lock = asyncio.Lock()
        self._available = asyncio.Event()
        self._state_listeners: list[HeadlessStateListener] = []
        operations = (
            getattr(clients[0], "operations", None)
            if clients
            else None
        ) or HeadlessOperationTracker()
        client_spawner = getattr(clients[0], "spawn", None) if clients else None
        task_spawner = spawn or cast(
            "TaskSpawner",
            client_spawner or asyncio.create_task,
        )
        self._dispatcher = HeadlessRequestDispatcher(
            [
                HeadlessWorkerSlot(
                    name=worker.name,
                    user_id=worker.user_id,
                    client=worker.client,
                )
                for worker in self._workers
            ],
            task_spawner,
        )
        self._game = PooledHeadlessGame(self._dispatcher, operations)

    @property
    def configured(self) -> bool:
        return bool(self._workers)

    @property
    def user_id_text(self) -> str:
        return ", ".join(str(worker.user_id) for worker in self._workers) or "未配置"

    @property
    def healthy_worker_count(self) -> int:
        return self._dispatcher.healthy_worker_count

    @property
    def configured_worker_count(self) -> int:
        return self._dispatcher.configured_worker_count

    @property
    def reconnect_times(self) -> list[str]:
        return self._notices.parsed_reconnect_check_times

    def login_failure_reason(self) -> str | None:
        failures = [
            failure
            for worker in self._workers
            if (failure := self._worker_failure(worker)) is not None
        ]
        if len(failures) == len(self._workers):
            if len(failures) == 1 and len(self._workers) == 1:
                return failures[0].partition(": ")[2]
            return "；".join(failures) or HEADLESS_CONFIG_MISSING_MESSAGE
        return None

    @staticmethod
    def _worker_failure(worker: _HeadlessWorkerRuntime) -> str | None:
        try:
            worker.client.get_client()
        except Exception as error:  # noqa: BLE001
            return f"{worker.name}({worker.user_id}): {error}"
        return None

    def get_game(self) -> HeadlessGame:
        if self.healthy_worker_count <= 0:
            message = "Headless Seer worker pool is unavailable"
            raise NotLoggedInError(message)
        return self._game

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
        if not self._workers:
            raise RuntimeError(HEADLESS_CONFIG_MISSING_MESSAGE)
        results = await asyncio.gather(
            *(self._login_worker(worker) for worker in self._workers),
            return_exceptions=True,
        )
        successful = [
            int(result)
            for result in results
            if isinstance(result, int)
        ]
        if not successful:
            errors = "；".join(
                str(result)
                for result in results
                if isinstance(result, BaseException)
            )
            raise RuntimeError(errors or "无头工作账号均未登录成功")
        self._dispatcher.dispatch()
        logger.info(
            "headless worker pool ready: healthy=%s configured=%s accounts=%s",
            self.healthy_worker_count,
            self.configured_worker_count,
            ",".join(str(user_id) for user_id in successful),
        )
        return successful[0]

    async def _login_worker(self, worker: _HeadlessWorkerRuntime) -> int:
        try:
            game = worker.client.get_client()
            if game.is_logged_in:
                await self._record_worker_state(
                    worker,
                    connected=True,
                    reason="",
                    source="登录复用",
                    notify=False,
                )
                return worker.user_id
        except (DisconnectedError, NotLoggedInError):
            pass
        game = await worker.client.login(
            HeadlessLoginRequest(
                user_id=worker.user_id,
                password=worker.password,
                login_server_url=self._connection.login_server_addr,
                heartbeat_interval=self._connection.heartbeat_interval,
                request_timeout_seconds=self._connection.request_timeout_seconds,
                reconnect_retries=self._connection.reconnect_retries,
                reconnect_delay=self._connection.reconnect_delay,
                reconnect_delay_max=self._connection.reconnect_delay_max,
                state_notifier=lambda **kwargs: self._mark_worker_game_state(
                    worker,
                    **kwargs,
                ),
                request_interval_seconds=self._request_interval_seconds,
            )
        )
        if not game.is_logged_in:
            message = (
                f"{worker.name}({worker.user_id}) 登录未完成，已进入自动重连"
            )
            raise RuntimeError(message)
        await self._record_worker_state(
            worker,
            connected=True,
            reason="",
            source="登录成功",
            notify=False,
        )
        return worker.user_id

    async def start(self) -> None:
        if not self.configured:
            logger.warning("无头客户端未配置米米号或密码，跳过登录")
            return
        try:
            await self.login()
        except Exception:
            logger.exception("无头工作池登录失败")

    async def shutdown(self) -> None:
        for worker in self._workers:
            worker.client.shutdown()

    async def check_on_connect(self) -> None:
        if not self.configured:
            return

        reason = self.login_failure_reason()
        if reason is None:
            await self._refresh_worker_states(source="启动检查", notify=False)
            return

        await self._refresh_worker_states(source="启动检查", notify=False)
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
            await self._refresh_worker_states(
                source=f"定时检测 {scheduled_time}", notify=False
            )
            return

        await self._refresh_worker_states(source=f"定时检测 {scheduled_time}")
        try:
            await self.login()
        except Exception:
            logger.exception(
                "headless reconnect check failed at %s",
                scheduled_time,
            )
            await self._refresh_worker_states(source=f"定时重连 {scheduled_time}")
            return

        await self._refresh_worker_states(source=f"定时重连 {scheduled_time}")

    async def mark_available(
        self,
        *,
        source: str,
        user_id: int | None = None,
        notify: bool = True,
    ) -> None:
        worker = self._worker_for_user_id(user_id)
        if worker is None and user_id is None:
            if len(self._workers) == 1:
                worker = self._workers[0]
            else:
                await self._refresh_worker_states(source=source, notify=notify)
                return
        if worker is not None:
            await self._record_worker_state(
                worker,
                connected=True,
                reason="",
                source=source,
                notify=notify,
            )

    async def mark_unavailable(
        self,
        reason: str,
        *,
        source: str,
        user_id: int | None = None,
        notify: bool = True,
    ) -> None:
        worker = self._worker_for_user_id(user_id)
        if worker is None and user_id is None:
            if len(self._workers) == 1:
                worker = self._workers[0]
            else:
                await self._refresh_worker_states(source=source, notify=notify)
                return
        if worker is not None:
            await self._record_worker_state(
                worker,
                connected=False,
                reason=reason,
                source=source,
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
        worker = self._worker_for_user_id(user_id)
        if worker is None:
            logger.warning("unknown headless worker state update: user_id=%s", user_id)
            return
        await self._record_worker_state(
            worker,
            connected=connected,
            reason=reason,
            source=source,
            notify=True,
        )

    async def _mark_worker_game_state(
        self,
        worker: _HeadlessWorkerRuntime,
        *,
        connected: bool,
        reason: str,
        source: str,
        user_id: int | None,
    ) -> None:
        del user_id
        await self._record_worker_state(
            worker,
            connected=connected,
            reason=reason,
            source=source,
            notify=True,
        )

    async def _refresh_worker_states(
        self,
        *,
        source: str,
        notify: bool = True,
    ) -> None:
        for worker in self._workers:
            connected = True
            reason = ""
            try:
                worker.client.get_client()
            except Exception as error:  # noqa: BLE001
                connected = False
                reason = str(error)
            await self._record_worker_state(
                worker,
                connected=connected,
                reason=reason,
                source=source,
                notify=notify,
            )

    async def _record_worker_state(
        self,
        worker: _HeadlessWorkerRuntime,
        *,
        connected: bool,
        reason: str,
        source: str,
        notify: bool,
    ) -> None:
        now = self._now()
        async with self._state_lock:
            worker_previous = worker.state.connected
            if worker_previous == connected:
                return
            worker_offline_since = worker.state.offline_since
            worker.state.connected = connected
            worker.state.offline_since = None if connected else now

            aggregate_previous = self._state.connected
            aggregate_connected = any(
                item.state.connected is True for item in self._workers
            )
            self._state.connected = aggregate_connected
            if aggregate_connected:
                self._available.set()
            else:
                self._available.clear()
                self._state.offline_since = self._state.offline_since or now
            if aggregate_connected and not aggregate_previous:
                self._state.offline_since = None

        if aggregate_previous != aggregate_connected:
            await self._notify_state_listeners(
                previous=aggregate_previous,
                connected=aggregate_connected,
                reason=reason,
                source=source,
            )
        if connected:
            self._dispatcher.dispatch()

        if worker_previous is None or not notify or not self._state_notifications:
            return
        if in_headless_notice_quiet_window(now):
            logger.info(
                "headless state notice suppressed by quiet window: %s -> %s (%s)",
                worker_previous,
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
                user_id=worker.user_id,
                reason=reason.strip() or "状态未知",
                source=source.strip() or "状态检测",
                offline_duration=_format_offline_duration(
                    now - worker_offline_since
                    if connected and worker_offline_since is not None
                    else None
                ),
            ),
            action_name="headless state notice",
            interval_seconds=1.2,
            subscription_key="headless_seer_notice",
        )

    def _worker_for_user_id(
        self,
        user_id: int | None,
    ) -> _HeadlessWorkerRuntime | None:
        if user_id is None:
            return None
        return next(
            (worker for worker in self._workers if worker.user_id == user_id),
            None,
        )

    def _first_healthy_worker(self) -> _HeadlessWorkerRuntime | None:
        for worker in self._workers:
            try:
                worker.client.get_client()
            except Exception:  # noqa: BLE001
                continue
            return worker
        return self._workers[0] if len(self._workers) == 1 else None

    def cancel_waiting_background(self, error: Exception) -> None:
        self._dispatcher.cancel_waiting_background(error)

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
