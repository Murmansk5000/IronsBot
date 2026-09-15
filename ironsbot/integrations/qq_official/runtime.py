# SPDX-License-Identifier: MIT
"""Tencent SDK lifecycle and passive-command runtime."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import TYPE_CHECKING

from qqbot_agent_sdk.api_client import QQApiClient
from qqbot_agent_sdk.event_parser import EventParser
from qqbot_agent_sdk.media_loader import MediaUploader
from qqbot_agent_sdk.session_store import WSSessionStore
from qqbot_agent_sdk.websocket import QQWebSocket, WSCallbacks

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import reference_digest
from ironsbot.integrations.qq_official.api_errors import QQOfficialHttpClient
from ironsbot.integrations.qq_official.identity import (
    qq_official_event_mentions_bot,
    qq_official_incoming_message,
)
from ironsbot.integrations.qq_official.inbound_deduplication import (
    QQOfficialInboundDeduplicator,
)
from ironsbot.integrations.qq_official.media_upload import QQOfficialMediaUpload
from ironsbot.integrations.qq_official.sdk_client import TencentQQClient
from ironsbot.integrations.qq_official.token_lifecycle import QQOfficialTokenObserver
from ironsbot.services.portable_reply import PortableReply, deliver_portable_reply

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from httpx import AsyncClient
    from qqbot_agent_sdk.event_parser import InboundEvent

    from ironsbot.core.outbound import OutboundMessenger, SendResult
    from ironsbot.core.platform import IncomingMessageRef
    from ironsbot.services.portable_commands import PortableCommandRouter
    from ironsbot.services.portable_reply import DeliveryStage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QQOfficialRuntimeAccount:
    app_id: str
    secret: str
    required: bool = False
    custom_keyboards: bool = False
    label: str = ""


class QQOfficialConnectionState(str, Enum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class QQOfficialAccountHealth:
    account: str
    required: bool
    state: QQOfficialConnectionState
    error: str | None = None


class QQOfficialStartupError(RuntimeError):
    def __init__(self, accounts: tuple[str, ...]) -> None:
        self.accounts = accounts
        super().__init__(
            "Required official accounts failed to become ready: "
            + ", ".join(accounts)
        )


@dataclass(slots=True)
class _AccountLifecycle:
    account: str
    required: bool
    state: QQOfficialConnectionState = QQOfficialConnectionState.STOPPED
    error: str | None = None
    _event: asyncio.Event | None = None
    _loop: asyncio.AbstractEventLoop | None = None
    _lock: Lock = field(default_factory=Lock)

    def prepare(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self.state = QQOfficialConnectionState.STARTING
            self.error = None
            self._loop = loop
            self._event = asyncio.Event()

    async def wait_until_settled(self, timeout_seconds: float) -> None:
        with self._lock:
            event = self._event
        if event is None:
            msg = f"official account was not prepared: {self.account}"
            raise RuntimeError(msg)
        await asyncio.wait_for(event.wait(), timeout=timeout_seconds)

    def ready(self) -> None:
        self._transition(QQOfficialConnectionState.READY, error=None, signal=True)

    def disconnected(self) -> None:
        with self._lock:
            if self.state in {
                QQOfficialConnectionState.STOPPED,
                QQOfficialConnectionState.FAILED,
                QQOfficialConnectionState.DEGRADED,
            }:
                return
        self._transition(QQOfficialConnectionState.RECONNECTING)

    def startup_failed(self, error: str) -> None:
        state = (
            QQOfficialConnectionState.FAILED
            if self.required
            else QQOfficialConnectionState.DEGRADED
        )
        self._transition(state, error=error, signal=True)

    def fatal(self, code: str, message: str) -> None:
        self.startup_failed(f"{code}: {message}")

    def stopped(self) -> None:
        self._transition(QQOfficialConnectionState.STOPPED, error=None, signal=True)

    def snapshot(self) -> QQOfficialAccountHealth:
        with self._lock:
            return QQOfficialAccountHealth(
                account=self.account,
                required=self.required,
                state=self.state,
                error=self.error,
            )

    def _transition(
        self,
        state: QQOfficialConnectionState,
        *,
        error: str | None = None,
        signal: bool = False,
    ) -> None:
        with self._lock:
            if self.state is QQOfficialConnectionState.STOPPED and state not in {
                QQOfficialConnectionState.STARTING,
                QQOfficialConnectionState.STOPPED,
            }:
                return
            self.state = state
            self.error = error
            loop = self._loop
            event = self._event
        if signal and loop is not None and event is not None and not loop.is_closed():
            loop.call_soon_threadsafe(event.set)


@dataclass(slots=True)
class _SessionState:
    app_id: str
    store: WSSessionStore
    session_id: str | None
    sequence: int | None
    dirty: bool = False
    lock: Lock = field(default_factory=Lock)

    @classmethod
    def load(cls, app_id: str, root: Path) -> _SessionState:
        store = WSSessionStore(str(root / app_id))
        persisted = store.get(app_id)
        resumable = persisted.is_resumable and persisted.is_fresh()
        return cls(
            app_id,
            store,
            persisted.session_id if resumable else None,
            persisted.seq if resumable else None,
            lock=Lock(),
        )

    def get(self) -> tuple[str | None, int | None]:
        with self.lock:
            return self.session_id, self.sequence

    def set(self, session_id: str | None, sequence: int | None) -> None:
        with self.lock:
            self.session_id = session_id
            self.sequence = sequence
            self.dirty = True
        if session_id is None and sequence is None:
            self.store.clear(self.app_id)

    def flush(self) -> None:
        with self.lock:
            if not self.dirty or self.session_id is None:
                return
            session_id = self.session_id
            sequence = self.sequence
            self.dirty = False
        self.store.save(self.app_id, session_id, sequence)


@dataclass(slots=True)
class _Connection:
    api: QQApiClient
    tokens: QQOfficialTokenObserver
    sender: TencentQQClient
    websocket: QQWebSocket
    session: _SessionState
    lifecycle: _AccountLifecycle
    started: bool = False


class QQOfficialRuntime:
    """Own one official SDK connection and token cache per configured AppID."""

    def __init__(
        self,
        accounts: tuple[QQOfficialRuntimeAccount, ...],
        *,
        http_client: AsyncClient,
        session_root: Path,
        startup_timeout_seconds: float = 15.0,
    ) -> None:
        if startup_timeout_seconds <= 0:
            msg = "QQ Official startup timeout must be positive"
            raise ValueError(msg)
        self._startup_timeout_seconds = startup_timeout_seconds
        self._inbound_deduplicator = QQOfficialInboundDeduplicator(
            session_root / "inbound.sqlite"
        )
        self._router: PortableCommandRouter | None = None
        self._messenger: OutboundMessenger | None = None
        self._connections: dict[str, _Connection] = {}
        for index, account in enumerate(accounts, start=1):
            if account.app_id in self._connections:
                msg = "duplicate official application identifier"
                raise ValueError(msg)
            label = account.label.strip() or f"account-{index}"
            api = QQApiClient(
                account.app_id,
                account.secret,
                f"IronsBot:{label}",
            )
            api.setup(QQOfficialHttpClient(http_client))
            tokens = QQOfficialTokenObserver(label)
            session = _SessionState.load(account.app_id, session_root)
            lifecycle = _AccountLifecycle(label, account.required)
            callbacks = self._callbacks(
                account.app_id,
                api,
                tokens,
                session,
                lifecycle,
            )
            self._connections[account.app_id] = _Connection(
                api=api,
                tokens=tokens,
                sender=TencentQQClient(
                    api,
                    QQOfficialMediaUpload(
                        MediaUploader(
                            api,
                            http_client,
                            log_tag=f"IronsBot:{label}",
                        ),
                        session_root / "media",
                    ),
                    custom_keyboards=account.custom_keyboards,
                    token_observer=tokens,
                ),
                websocket=QQWebSocket(
                    callbacks=callbacks,
                    log_tag=f"IronsBot:{label}",
                ),
                session=session,
                lifecycle=lifecycle,
            )

    @property
    def account_ids(self) -> tuple[str, ...]:
        return tuple(self._connections)

    def sender(self, app_id: str) -> TencentQQClient | None:
        connection = self._connections.get(app_id)
        return connection.sender if connection is not None else None

    @property
    def account_health(self) -> tuple[QQOfficialAccountHealth, ...]:
        return tuple(
            connection.lifecycle.snapshot() for connection in self._connections.values()
        )

    def bind(
        self,
        router: PortableCommandRouter,
        messenger: OutboundMessenger,
    ) -> None:
        if self._router is not None or self._messenger is not None:
            msg = "QQ Official runtime is already bound"
            raise RuntimeError(msg)
        self._router = router
        self._messenger = messenger

    async def start(self) -> None:
        if self._router is None or self._messenger is None:
            msg = "QQ Official runtime must be bound before startup"
            raise RuntimeError(msg)
        loop = asyncio.get_running_loop()
        await asyncio.gather(
            *(
                _start_connection(
                    connection.lifecycle.account,
                    connection,
                    loop,
                    timeout_seconds=self._startup_timeout_seconds,
                )
                for connection in self._connections.values()
            )
        )
        failed_required = tuple(
            health.account
            for health in self.account_health
            if health.required and health.state is not QQOfficialConnectionState.READY
        )
        if failed_required:
            await self.stop()
            raise QQOfficialStartupError(failed_required)

    async def stop(self) -> None:
        tasks = [
            connection.websocket.async_stop()
            for connection in self._connections.values()
            if connection.started
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for connection in self._connections.values():
            connection.session.flush()
            connection.started = False
            connection.lifecycle.stopped()

    async def handle_event(
        self,
        app_id: str,
        event_type: str,
        raw: Mapping[str, object],
    ) -> None:
        event = EventParser.parse(event_type, dict(raw))
        if event is None:
            logger.warning(
                "QQ Official inbound event rejected by parser: "
                "account=%s event_type=%s",
                self._connections[app_id].lifecycle.account,
                event_type,
            )
            return
        router = self._router
        messenger = self._messenger
        if router is None or messenger is None:
            logger.error("QQ Official event arrived before runtime binding")
            return
        incoming = qq_official_incoming_message(event, account_id=app_id)
        if not await self._inbound_deduplicator.claim(
            app_id=app_id,
            event_type=event_type,
            message_id=incoming.message_id,
        ):
            logger.info(
                "QQ Official duplicate inbound message ignored: "
                "account=%s event_type=%s message_ref=%s",
                self._connections[app_id].lifecycle.account,
                event_type,
                reference_digest(incoming.message_id),
            )
            return
        context = MessageInputContext(
            incoming,
            mentions_bot=qq_official_event_mentions_bot(event),
        )
        recognized = router.recognizes(context)
        logger.info(
            "QQ Official inbound routed: account=%s event_type=%s "
            "input_kind=%s recognized=%s",
            self._connections[app_id].lifecycle.account,
            event_type,
            context.kind.value,
            recognized,
        )
        if not recognized:
            return
        try:
            reply = await router.dispatch(context)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - platform boundary
            logger.error(  # noqa: TRY400 - exception text may contain private data
                "QQ Official command dispatch failed: account=%s event_type=%s "
                "kind=%s error_type=%s",
                self._connections[app_id].lifecycle.account,
                event_type,
                incoming.conversation.kind,
                type(error).__name__,
            )
            reply = PortableReply(
                OutboundMessage.from_text("❌ 命令执行失败，请稍后再试。")
            )
        if reply is not None:
            await deliver_qq_official_reply(
                messenger,
                incoming,
                reply,
                account_label=self._connections[app_id].lifecycle.account,
            )

    def _callbacks(
        self,
        app_id: str,
        api: QQApiClient,
        tokens: QQOfficialTokenObserver,
        session: _SessionState,
        lifecycle: _AccountLifecycle,
    ) -> WSCallbacks:
        account_label = lifecycle.account

        async def on_message_event(
            event_type: str,
            raw: dict[str, object],
        ) -> None:
            await self.handle_event(app_id, event_type, raw)

        def connected() -> None:
            lifecycle.ready()
            logger.info("QQ Official ready: account=%s", account_label)

        def disconnected() -> None:
            lifecycle.disconnected()
            logger.warning("QQ Official disconnected: account=%s", account_label)

        def fatal_error(code: str, message: str) -> None:
            lifecycle.fatal(code, message)
            logger.error(
                "QQ Official fatal error: account=%s code=%s message=%s",
                account_label,
                code,
                message,
            )

        return WSCallbacks(
            on_message_event=on_message_event,
            on_connected=connected,
            on_disconnected=disconnected,
            on_fatal_error=fatal_error,
            get_token=lambda: tokens.ensure_sync(api),
            get_gateway_url=api.get_gateway_url_sync,
            get_session=session.get,
            set_session=session.set,
            set_heartbeat_interval=lambda _interval: None,
            clear_token=api.clear_token,
            fail_pending=lambda reason: logger.warning(
                "QQ Official pending operations failed: account=%s reason=%s",
                account_label,
                reason,
            ),
            on_heartbeat_ack=session.flush,
        )


async def _start_connection(
    account_label: str,
    connection: _Connection,
    loop: asyncio.AbstractEventLoop,
    *,
    timeout_seconds: float,
) -> bool:
    connection.lifecycle.prepare(loop)
    try:
        await connection.tokens.ensure(connection.api)
        gateway_url = await connection.api.get_gateway_url()
        connection.websocket.start(gateway_url, loop)
        connection.started = True
        logger.info("QQ Official connection starting: account=%s", account_label)
        await connection.lifecycle.wait_until_settled(timeout_seconds)
    except TimeoutError:
        message = f"READY timeout after {timeout_seconds:g}s"
        connection.lifecycle.startup_failed(message)
        logger.warning("QQ Official %s: account=%s", message, account_label)
        return False
    except Exception as error:
        connection.lifecycle.startup_failed(
            f"{type(error).__name__}: {error}",
        )
        logger.exception(
            "QQ Official connection failed to start: account=%s",
            account_label,
        )
        return False
    return connection.lifecycle.snapshot().state is QQOfficialConnectionState.READY


async def deliver_qq_official_reply(
    messenger: OutboundMessenger,
    incoming: IncomingMessageRef,
    reply: PortableReply,
    *,
    account_label: str = "official-account",
) -> None:
    """Commit delivery-aware work only after the official API accepts a reply."""

    from ironsbot.core.outbound import ReplyContext

    context = ReplyContext.from_message(incoming)

    def on_sent(stage: DeliveryStage, result: SendResult) -> None:
        if result.delivered:
            _log_delivery_success(incoming, stage=stage, account_label=account_label)
        else:
            _log_delivery_failure(
                incoming, result, stage=stage, account_label=account_label,
            )

    def on_follow_up_error(error: Exception) -> OutboundMessage:
        logger.exception(
            "QQ Official deferred operation failed: account=%s kind=%s ref=%s",
            account_label,
            incoming.conversation.kind,
            reference_digest(incoming.conversation.id),
        )
        return OutboundMessage.from_text(
            f"❌ 操作执行失败：{type(error).__name__}"
        )

    await deliver_portable_reply(
        reply,
        lambda message: messenger.reply(context, message),
        on_sent=on_sent,
        on_follow_up_error=on_follow_up_error,
    )


def qq_official_event_is_supported(
    event: InboundEvent,
    *,
    account_id: str,
    router: PortableCommandRouter,
) -> bool:
    incoming = qq_official_incoming_message(event, account_id=account_id)
    return router.recognizes(
        MessageInputContext(
            incoming,
            mentions_bot=qq_official_event_mentions_bot(event),
        )
    )


def _log_delivery_failure(
    incoming: IncomingMessageRef,
    result: SendResult,
    *,
    stage: str,
    account_label: str = "official-account",
) -> None:
    logger.warning(
        "QQ Official reply failed: stage=%s account=%s kind=%s ref=%s "
        "code=%s message=%s trace_id=%s",
        stage,
        account_label,
        incoming.conversation.kind,
        reference_digest(incoming.conversation.id),
        result.error_code,
        result.error_message,
        result.trace_id,
    )


def _log_delivery_success(
    incoming: IncomingMessageRef,
    *,
    stage: str,
    account_label: str,
) -> None:
    logger.info(
        "QQ Official reply delivered: stage=%s account=%s kind=%s",
        stage,
        account_label,
        incoming.conversation.kind,
    )
