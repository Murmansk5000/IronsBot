from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from pydantic import AnyWebsocketUrl

from ironsbot.app.application import Application
from ironsbot.app.lifecycle import TaskOwner
from ironsbot.config.models.transport import OneBotConfig
from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.plugin_install import PluginContribution, PluginContributionCatalog
from ironsbot.integrations.onebot.connections import OneBotConnections
from ironsbot.integrations.onebot.notice_ingress import OneBotNoticeIngress
from ironsbot.integrations.onebot.received_messages import OneBotReceivedMessages

ONEBOT_ROUTE_COUNT = 6


@pytest.mark.parametrize("onebot_enabled", [False, True])
def test_application_binds_shared_ingress_once_without_native_installation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    onebot_enabled: bool,
) -> None:
    calls: list[str] = []
    transport = SimpleNamespace(start=AsyncMock(), close=AsyncMock())

    def build_transport(**options: Any) -> SimpleNamespace:
        calls.append("adapter")
        received = options["received"].__self__
        assert isinstance(received, OneBotReceivedMessages)
        assert received.admission is application.resources.onebot_admission
        assert received.router is router
        assert received.messenger is application.resources.onebot_messenger
        assert received.red_packets is None
        assert received.nicknames == frozenset({"example nickname"})
        assert options["config"] is application.settings.bot.onebot
        assert options["access_token"] == "test-token"
        notices = options["notices"].__self__
        assert isinstance(notices, OneBotNoticeIngress)
        assert notices.admission is received.admission
        assert notices.messenger is received.messenger
        assert notices.spawn == application.task_owner.create
        assert notices.poke is notices.audit is notices.red_packets is None
        assert options["spawn"] == application.task_owner.create
        assert options["request_http"].client is application.http_clients.origin
        assert options["connections"] is application.resources.onebot_connections
        assert options["observer"] is application.lifecycle
        return transport

    commands = CommandCatalog()
    contributions = (PluginContribution(id="example"),)
    application = Application(
        settings=cast(
            "Any",
            SimpleNamespace(
                bot=SimpleNamespace(
                    matcher_priority=SimpleNamespace(red_packet_notice=0),
                    onebot=OneBotConfig(
                        enabled=onebot_enabled,
                        nicknames={"example nickname"},
                        ws_urls={AnyWebsocketUrl("ws://example.test/onebot")},
                    ),
                    onebot_token="test-token",
                )
            ),
        ),
        asgi=FastAPI(openapi_url=None, docs_url=None, redoc_url=None),
        scheduler=cast("Any", SimpleNamespace(start=Mock(), shutdown=AsyncMock())),
        file_logging=cast("Any", object()),
        http_clients=cast("Any", SimpleNamespace(origin=object())),
        databases=cast("Any", object()),
        resources=cast(
            "Any",
            SimpleNamespace(
                commands=commands,
                query_sessions=object(),
                features=object(),
                contribution_catalog=PluginContributionCatalog(),
                onebot_messenger=object(),
                onebot_admission=object(),
                onebot_connections=OneBotConnections(),
                qq_official=None,
            ),
        ),
        extension_services=cast("Any", object()),
        task_owner=TaskOwner(),
        known_features=(),
        required_plugin_features=frozenset(),
        contributions=(),
    )

    application.configure(contributions)
    monkeypatch.setattr(
        "ironsbot.integrations.onebot.transport.OneBotTransport",
        build_transport,
    )
    router = cast("Any", object())
    application.install(router)
    application.install(router)

    assert calls == (["adapter"] if onebot_enabled else [])
    assert len(application.asgi.routes) == (ONEBOT_ROUTE_COUNT if onebot_enabled else 0)
    assert application.onebot_transport is (transport if onebot_enabled else None)
    assert application.lifecycle is not None
    assert application.lifecycle.shutdown_hooks == (
        (("onebot_transport", transport.close),) if onebot_enabled else ()
    )

    async def running() -> None:
        async with application.asgi.router.lifespan_context(application.asgi):
            if onebot_enabled:
                transport.start.assert_awaited_once()
            else:
                transport.start.assert_not_awaited()

    asyncio.run(running())
    if onebot_enabled:
        transport.close.assert_awaited_once()
    else:
        transport.close.assert_not_awaited()
