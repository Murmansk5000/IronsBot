# SPDX-License-Identifier: MIT
"""Tencent SDK lifecycle and passive-command runtime."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING

from qqbot_agent_sdk.api_client import QQApiClient
from qqbot_agent_sdk.event_parser import EventParser
from qqbot_agent_sdk.session_store import WSSessionStore
from qqbot_agent_sdk.websocket import QQWebSocket, WSCallbacks

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage
from ironsbot.integrations.qq_official.api_errors import QQOfficialHttpClient
from ironsbot.integrations.qq_official.identity import (
    is_qq_official_reply_event,
    qq_official_event_mentions_bot,
    qq_official_incoming_message,
)
from ironsbot.integrations.qq_official.sdk_client import TencentQQClient

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from httpx import AsyncClient
    from qqbot_agent_sdk.event_parser import InboundEvent

    from ironsbot.core.outbound import OutboundMessenger, SendResult
    from ironsbot.core.platform import IncomingMessageRef
    from ironsbot.services.portable_commands import PortableCommandRouter
    from ironsbot.services.portable_reply import PortableReply

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QQOfficialRuntimeAccount:
    app_id: str
    secret: str
    custom_keyboards: bool = False


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
    sender: TencentQQClient
    websocket: QQWebSocket
    session: _SessionState
    started: bool = False


class QQOfficialRuntime:
    """Own one official SDK connection and token cache per configured AppID."""

    def __init__(
        self,
        accounts: tuple[QQOfficialRuntimeAccount, ...],
        *,
        http_client: AsyncClient,
        session_root: Path,
    ) -> None:
        self._router: PortableCommandRouter | None = None
        self._messenger: OutboundMessenger | None = None
        self._connections: dict[str, _Connection] = {}
        for account in accounts:
            if account.app_id in self._connections:
                msg = f"duplicate QQ Official AppID: {account.app_id}"
                raise ValueError(msg)
            api = QQApiClient(
                account.app_id,
                account.secret,
                f"IronsBot:{account.app_id}",
            )
            api.setup(QQOfficialHttpClient(http_client))
            session = _SessionState.load(account.app_id, session_root)
            callbacks = self._callbacks(account.app_id, api, session)
            self._connections[account.app_id] = _Connection(
                api=api,
                sender=TencentQQClient(
                    api,
                    custom_keyboards=account.custom_keyboards,
                ),
                websocket=QQWebSocket(
                    callbacks=callbacks,
                    log_tag=f"IronsBot:{account.app_id}",
                ),
                session=session,
            )

    @property
    def account_ids(self) -> tuple[str, ...]:
        return tuple(self._connections)

    def sender(self, app_id: str) -> TencentQQClient | None:
        connection = self._connections.get(app_id)
        return connection.sender if connection is not None else None

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
        started = 0
        for app_id, connection in self._connections.items():
            if await _start_connection(app_id, connection, loop):
                started += 1
        if self._connections and started == 0:
            msg = "No QQ Official account could start"
            raise RuntimeError(msg)

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

    async def handle_event(
        self,
        app_id: str,
        event_type: str,
        raw: Mapping[str, object],
    ) -> None:
        event = EventParser.parse(event_type, dict(raw))
        if event is None or is_qq_official_reply_event(event):
            return
        router = self._router
        messenger = self._messenger
        if router is None or messenger is None:
            logger.error("QQ Official event arrived before runtime binding")
            return
        incoming = qq_official_incoming_message(event, account_id=app_id)
        context = MessageInputContext(
            incoming,
            mentions_bot=qq_official_event_mentions_bot(event),
        )
        if not router.recognizes(context):
            return
        reply = await router.dispatch(context)
        if reply is not None:
            await deliver_qq_official_reply(messenger, incoming, reply)

    def _callbacks(
        self,
        app_id: str,
        api: QQApiClient,
        session: _SessionState,
    ) -> WSCallbacks:
        async def on_message_event(
            event_type: str,
            raw: dict[str, object],
        ) -> None:
            await self.handle_event(app_id, event_type, raw)

        return WSCallbacks(
            on_message_event=on_message_event,
            on_connected=lambda: logger.info(
                "QQ Official connected: app_id=%s", app_id
            ),
            on_disconnected=lambda: logger.warning(
                "QQ Official disconnected: app_id=%s", app_id
            ),
            on_fatal_error=lambda code, message: logger.error(
                "QQ Official fatal error: app_id=%s code=%s message=%s",
                app_id,
                code,
                message,
            ),
            get_token=api.ensure_token_sync,
            get_gateway_url=api.get_gateway_url_sync,
            get_session=session.get,
            set_session=session.set,
            set_heartbeat_interval=lambda _interval: None,
            clear_token=api.clear_token,
            fail_pending=lambda reason: logger.warning(
                "QQ Official pending operations failed: app_id=%s reason=%s",
                app_id,
                reason,
            ),
            on_heartbeat_ack=session.flush,
        )


async def _start_connection(
    app_id: str,
    connection: _Connection,
    loop: asyncio.AbstractEventLoop,
) -> bool:
    try:
        await connection.api.ensure_token()
        gateway_url = await connection.api.get_gateway_url()
        connection.websocket.start(gateway_url, loop)
        connection.started = True
        logger.info("QQ Official connection starting: app_id=%s", app_id)
    except Exception:
        logger.exception("QQ Official connection failed to start: app_id=%s", app_id)
        return False
    return True


async def deliver_qq_official_reply(
    messenger: OutboundMessenger,
    incoming: IncomingMessageRef,
    reply: PortableReply,
) -> None:
    """Commit delivery-aware work only after the official API accepts a reply."""

    from ironsbot.core.outbound import ReplyContext

    context = ReplyContext.from_message(incoming)
    result = await messenger.reply(context, reply.message)
    if not result.delivered:
        reply.delivery_failed()
        _log_delivery_failure(incoming, result, stage="initial")
        return
    reply.delivered()
    for additional in reply.additional_messages:
        additional_result = await messenger.reply(context, additional)
        if not additional_result.delivered:
            _log_delivery_failure(incoming, additional_result, stage="additional")
            return
    if reply.follow_up is None:
        return
    try:
        follow_up = await reply.follow_up()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception(
            "QQ Official deferred operation failed: account=%s kind=%s id=%s",
            incoming.conversation.account_id,
            incoming.conversation.kind,
            incoming.conversation.id,
        )
        follow_up = OutboundMessage.from_text(
            f"❌ 操作执行失败：{type(error).__name__}"
        )
    follow_up_result = await messenger.reply(context, follow_up)
    if not follow_up_result.delivered:
        _log_delivery_failure(incoming, follow_up_result, stage="follow_up")


def qq_official_event_is_supported(
    event: InboundEvent,
    *,
    account_id: str,
    router: PortableCommandRouter,
) -> bool:
    if is_qq_official_reply_event(event):
        return False
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
) -> None:
    logger.warning(
        "QQ Official reply failed: stage=%s account=%s kind=%s id=%s "
        "code=%s message=%s trace_id=%s",
        stage,
        incoming.conversation.account_id,
        incoming.conversation.kind,
        incoming.conversation.id,
        result.error_code,
        result.error_message,
        result.trace_id,
    )
