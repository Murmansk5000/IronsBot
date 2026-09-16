from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from qqbot_agent_sdk.dto import MSG_TYPE_QUOTE
from qqbot_agent_sdk.event_parser import EventParser, InboundEvent

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.qq_official import runtime as runtime_module
from ironsbot.integrations.qq_official.identity import qq_official_incoming_message
from ironsbot.integrations.qq_official.runtime import (
    QQOfficialConnectionState,
    QQOfficialRuntime,
    QQOfficialRuntimeAccount,
    QQOfficialStartupError,
)

if TYPE_CHECKING:
    from pathlib import Path

    from qqbot_agent_sdk.websocket import WSCallbacks

    from ironsbot.core.outbound import OutboundMessenger
    from ironsbot.services.portable_commands import PortableCommandRouter


class _FakeApi:
    def __init__(self, app_id: str, _secret: str, _tag: str) -> None:
        self.app_id = app_id

    def setup(self, _client: object) -> None:
        pass

    async def ensure_token(self) -> str:
        return "test-token"

    async def get_gateway_url(self) -> str:
        return "wss://example.invalid"

    def ensure_token_sync(self) -> str:
        return "test-token"

    def get_gateway_url_sync(self) -> str:
        return "wss://example.invalid"

    def clear_token(self) -> None:
        pass


class _FakeWebSocket:
    connect_on_start = True
    instances: ClassVar[list[_FakeWebSocket]] = []

    def __init__(self, callbacks: WSCallbacks, log_tag: str) -> None:
        self.callbacks = callbacks
        self.log_tag = log_tag
        self.stopped = False
        self.instances.append(self)

    def start(
        self,
        _gateway_url: str,
        _loop: asyncio.AbstractEventLoop,
    ) -> None:
        if self.connect_on_start:
            self.callbacks.on_connected()

    async def async_stop(self) -> None:
        self.stopped = True


class _CountingRouter:
    def __init__(self) -> None:
        self.dispatch_count = 0

    def recognizes(self, _context: object) -> bool:
        return True

    async def dispatch(self, _context: object) -> None:
        self.dispatch_count += 1


def _install_fake_sdk(monkeypatch: pytest.MonkeyPatch, *, ready: bool) -> None:
    _FakeWebSocket.connect_on_start = ready
    _FakeWebSocket.instances.clear()
    monkeypatch.setattr(runtime_module, "QQApiClient", _FakeApi)
    monkeypatch.setattr(runtime_module, "QQWebSocket", _FakeWebSocket)


def _bind(runtime: QQOfficialRuntime) -> None:
    runtime.bind(
        cast("PortableCommandRouter", object()),
        cast("OutboundMessenger", object()),
    )


def test_official_sdk_parser_feeds_opaque_group_identity() -> None:
    raw = {
        "id": "message-id",
        "content": "@babyQ 帮助",
        "timestamp": "2026-09-14T00:00:00+08:00",
        "group_openid": "group-openid",
        "author": {
            "member_openid": "member-openid",
            "member_role": "admin",
        },
    }

    event = EventParser.parse("GROUP_AT_MESSAGE_CREATE", raw)

    assert event is not None
    incoming = qq_official_incoming_message(event, account_id="app-id")
    assert incoming.text == "帮助"
    assert incoming.actor == ActorRef(
        Platform.QQ_OFFICIAL,
        "member-openid",
        "member",
        "group-openid",
        "app-id",
    )
    assert incoming.conversation == ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-openid",
        "app-id",
    )
    assert incoming.group_role == "admin"


def test_runtime_keeps_clients_isolated_by_app_id(tmp_path: Path) -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            runtime = QQOfficialRuntime(
                (
                    QQOfficialRuntimeAccount("app-a", "secret-a"),
                    QQOfficialRuntimeAccount("app-b", "secret-b"),
                ),
                http_client=client,
                session_root=tmp_path,
            )

            assert runtime.account_ids == ("app-a", "app-b")
            assert runtime.sender("app-a") is not runtime.sender("app-b")
            assert runtime.sender("missing") is None

    asyncio.run(run())


def test_runtime_rejects_duplicate_app_ids(tmp_path: Path) -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            with pytest.raises(
                ValueError,
                match="duplicate official application identifier",
            ):
                QQOfficialRuntime(
                    (
                        QQOfficialRuntimeAccount("same-app", "secret-a"),
                        QQOfficialRuntimeAccount("same-app", "secret-b"),
                    ),
                    http_client=client,
                    session_root=tmp_path,
                )

    asyncio.run(run())


def test_runtime_rejects_app_ids_that_collide_after_normalization(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            with pytest.raises(
                ValueError,
                match="duplicate official application identifier",
            ):
                QQOfficialRuntime(
                    (
                        QQOfficialRuntimeAccount("same-app", "secret-a"),
                        QQOfficialRuntimeAccount(" same-app ", " secret-b "),
                    ),
                    http_client=client,
                    session_root=tmp_path,
                )

    asyncio.run(run())


@pytest.mark.parametrize(
    ("app_id", "secret", "message"),
    [
        ("   ", "secret", "AppID must not be empty"),
        ("app", "   ", "secret must not be empty"),
    ],
)
def test_runtime_account_rejects_empty_credentials(
    app_id: str,
    secret: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        QQOfficialRuntimeAccount(app_id, secret)


def test_runtime_claims_message_before_business_dispatch(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            runtime = QQOfficialRuntime(
                (
                    QQOfficialRuntimeAccount(
                        "private-app-id",
                        "secret",
                        label="preview",
                    ),
                ),
                http_client=client,
                session_root=tmp_path,
            )
            router = _CountingRouter()
            runtime.bind(
                cast("PortableCommandRouter", router),
                cast("OutboundMessenger", object()),
            )
            raw = {
                "id": "message-id",
                "content": "@babyQ 帮助",
                "timestamp": "2026-09-15T00:00:00+08:00",
                "group_openid": "group-openid",
                "author": {"member_openid": "member-openid"},
            }

            caplog.set_level("INFO", logger=runtime_module.__name__)
            await runtime.handle_event(
                "private-app-id",
                "GROUP_AT_MESSAGE_CREATE",
                raw,
            )
            await runtime.handle_event(
                "private-app-id",
                "GROUP_AT_MESSAGE_CREATE",
                raw,
            )

            assert router.dispatch_count == 1
            assert "account=preview" in caplog.text
            assert "input_kind=bot_mention recognized=True" in caplog.text
            assert "private-app-id" not in caplog.text
            assert "message-id" not in caplog.text
            assert "@babyQ 帮助" not in caplog.text

    asyncio.run(run())


def test_runtime_reports_parser_rejection_without_event_details(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            runtime = QQOfficialRuntime(
                (
                    QQOfficialRuntimeAccount(
                        "private-app-id",
                        "secret",
                        label="preview",
                    ),
                ),
                http_client=client,
                session_root=tmp_path,
            )
            _bind(runtime)
            caplog.set_level("INFO", logger=runtime_module.__name__)

            await runtime.handle_event(
                "private-app-id",
                "C2C_MESSAGE_CREATE",
                {
                    "id": "private-message-id",
                    "content": "private command body",
                    "author": {"username": "private-openid"},
                },
            )

            assert "inbound event rejected by parser" in caplog.text
            assert "account=preview" in caplog.text
            assert "event_type=C2C_MESSAGE_CREATE" in caplog.text
            assert "private-app-id" not in caplog.text
            assert "private-message-id" not in caplog.text
            assert "private command body" not in caplog.text
            assert "private-openid" not in caplog.text

    asyncio.run(run())


def test_sdk_callback_reports_inbound_failure_without_event_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def run() -> None:
        _install_fake_sdk(monkeypatch, ready=True)
        async with httpx.AsyncClient() as client:
            runtime = QQOfficialRuntime(
                (
                    QQOfficialRuntimeAccount(
                        "private-app-id",
                        "secret",
                        label="preview",
                    ),
                ),
                http_client=client,
                session_root=tmp_path,
            )
            _bind(runtime)
            handle_event = AsyncMock(
                side_effect=ValueError("private-message-id private command body")
            )
            monkeypatch.setattr(runtime, "handle_event", handle_event)
            callback = _FakeWebSocket.instances[0].callbacks.on_message_event
            raw = {
                "id": "private-message-id",
                "content": "private command body",
                "author": {"username": "private-openid"},
            }
            caplog.set_level("INFO", logger=runtime_module.__name__)

            await callback("C2C_MESSAGE_CREATE", raw)

            handle_event.assert_awaited_once_with(
                "private-app-id",
                "C2C_MESSAGE_CREATE",
                raw,
            )
            assert "inbound handling failed" in caplog.text
            assert "account=preview" in caplog.text
            assert "event_type=C2C_MESSAGE_CREATE" in caplog.text
            assert "error_type=ValueError" in caplog.text
            assert "private-app-id" not in caplog.text
            assert "private-message-id" not in caplog.text
            assert "private command body" not in caplog.text
            assert "private-openid" not in caplog.text

    asyncio.run(run())


def test_runtime_dispatches_user_quote_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        event = InboundEvent(
            event_type="C2C_MESSAGE_CREATE",
            chat_id="private-openid",
            user_id="private-openid",
            chat_scope="c2c",
            content="帮助",
            message_id="quote-message-id",
            timestamp="2099-01-01T00:00:00+08:00",
            message_type=MSG_TYPE_QUOTE,
            raw={"message_scene": {"ext": ["ref_msg_idx=quoted-message"]}},
        )
        monkeypatch.setattr(
            EventParser,
            "parse",
            staticmethod(lambda _event_type, _raw: event),
        )
        async with httpx.AsyncClient() as client:
            runtime = QQOfficialRuntime(
                (QQOfficialRuntimeAccount("private-app-id", "secret"),),
                http_client=client,
                session_root=tmp_path,
            )
            router = _CountingRouter()
            runtime.bind(
                cast("PortableCommandRouter", router),
                cast("OutboundMessenger", object()),
            )

            await runtime.handle_event(
                "private-app-id",
                "C2C_MESSAGE_CREATE",
                {},
            )

            assert router.dispatch_count == 1

    asyncio.run(run())


def test_required_account_waits_for_ready_and_tracks_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        _install_fake_sdk(monkeypatch, ready=True)
        async with httpx.AsyncClient() as client:
            runtime = QQOfficialRuntime(
                (QQOfficialRuntimeAccount("app", "secret", required=True),),
                http_client=client,
                session_root=tmp_path,
                startup_timeout_seconds=0.1,
            )
            _bind(runtime)

            await runtime.start()
            assert runtime.account_health[0].state is QQOfficialConnectionState.READY

            callbacks = _FakeWebSocket.instances[0].callbacks
            callbacks.on_disconnected()
            assert (
                runtime.account_health[0].state
                is QQOfficialConnectionState.RECONNECTING
            )
            callbacks.on_connected()
            assert runtime.account_health[0].state is QQOfficialConnectionState.READY

            callbacks.on_fatal_error("qq_fatal", "permission denied")
            health = runtime.account_health[0]
            assert health.state is QQOfficialConnectionState.FAILED
            assert health.error == "qq_fatal: permission denied"

            await runtime.stop()
            assert runtime.account_health[0].state is QQOfficialConnectionState.STOPPED
            assert _FakeWebSocket.instances[0].stopped

    asyncio.run(run())


def test_optional_account_timeout_is_degraded_without_blocking_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        _install_fake_sdk(monkeypatch, ready=False)
        async with httpx.AsyncClient() as client:
            runtime = QQOfficialRuntime(
                (QQOfficialRuntimeAccount("optional", "secret"),),
                http_client=client,
                session_root=tmp_path,
                startup_timeout_seconds=0.01,
            )
            _bind(runtime)

            await runtime.start()

            health = runtime.account_health[0]
            assert health.state is QQOfficialConnectionState.DEGRADED
            assert health.error == "READY timeout after 0.01s"
            await runtime.stop()

    asyncio.run(run())


def test_required_account_timeout_stops_runtime_and_blocks_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        _install_fake_sdk(monkeypatch, ready=False)
        async with httpx.AsyncClient() as client:
            runtime = QQOfficialRuntime(
                (QQOfficialRuntimeAccount("required", "secret", required=True),),
                http_client=client,
                session_root=tmp_path,
                startup_timeout_seconds=0.01,
            )
            _bind(runtime)

            with pytest.raises(QQOfficialStartupError) as caught:
                await runtime.start()

            assert caught.value.accounts == ("account-1",)
            assert runtime.account_health[0].state is QQOfficialConnectionState.STOPPED
            assert _FakeWebSocket.instances[0].stopped

    asyncio.run(run())


def test_optional_fatal_error_can_recover_to_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        _install_fake_sdk(monkeypatch, ready=True)
        async with httpx.AsyncClient() as client:
            runtime = QQOfficialRuntime(
                (QQOfficialRuntimeAccount("optional", "secret"),),
                http_client=client,
                session_root=tmp_path,
                startup_timeout_seconds=0.1,
            )
            _bind(runtime)
            await runtime.start()

            callbacks = _FakeWebSocket.instances[0].callbacks
            callbacks.on_fatal_error("qq_test", "unavailable")
            health = runtime.account_health[0]
            assert health.state is QQOfficialConnectionState.DEGRADED
            assert health.error == "qq_test: unavailable"

            callbacks.on_connected()
            assert runtime.account_health[0].state is QQOfficialConnectionState.READY
            await runtime.stop()

    asyncio.run(run())
