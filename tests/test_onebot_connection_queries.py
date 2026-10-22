from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from ironsbot.config.models.messaging import OutboundRateLimitConfig
from ironsbot.config.models.transport import OneBotRoutingConfig
from ironsbot.config.qq_references import QQReferenceResolver
from ironsbot.core.outbound import DeliveryHistoryStatus, ExecutionIdentity, SendResult
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.onebot.connections import OneBotConnections
from ironsbot.integrations.onebot.errors import OneBotActionError
from ironsbot.integrations.onebot.group_probe import OneBotGroupProbe
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from ironsbot.integrations.onebot.router import BotRouter
from ironsbot.services.onebot_routing import OneBotRoutingPolicy
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from pytest import LogCaptureFixture


@dataclass
class _Connection:
    self_id: str = "111"
    result: object = None
    error: Exception | None = None
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    async def call_api(self, api: str, **data: object) -> object:
        self.calls.append((api, data))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.asyncio
@pytest.mark.parametrize("member", [False, True])
@pytest.mark.parametrize("failure", [None, "action", "network"])
async def test_group_probe_uses_port_and_keeps_network_failures_distinct(
    caplog: LogCaptureFixture, failure: str | None, *, member: bool
) -> None:
    connection = _Connection(
        error=OneBotActionError(retcode=1200)
        if failure == "action"
        else ConnectionError("sensitive-network-detail")
        if failure == "network"
        else None,
    )
    probe = OneBotGroupProbe()
    operation = (
        probe.has_member(connection, group_id=456, user_id=789)
        if member
        else probe.can_access(connection, group_id=456)
    )
    if failure == "network":
        with pytest.raises(ConnectionError):
            await operation
    else:
        assert await operation is (failure is None)
    assert connection.calls == [
        (
            "get_group_member_info" if member else "get_group_info",
            {"group_id": 456, "no_cache": True, **({"user_id": 789} if member else {})},
        )
    ]
    assert "sensitive-action-detail" not in caplog.text
    assert "sensitive-network-detail" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["confirmed", "missing", "error"])
async def test_history_uses_minimal_port_without_resending(outcome: str) -> None:
    connection = _Connection(
        result={"message_id": -42 if outcome == "confirmed" else -43},
        error=ConnectionError("query transport unavailable")
        if outcome == "error"
        else None,
    )
    connections = OneBotConnections()
    connections.connect(connection)
    policy = OneBotRoutingPolicy(
        OneBotRoutingConfig(
            enabled=True,
            default_bot="worker",
            bot_aliases={"worker": 111},
            users={"owner": "worker"},
        ),
        QQReferenceResolver({}, {"owner": 789}),
    )
    runtime = build_test_runtime(outbound_config=OutboundRateLimitConfig(enabled=False))
    messenger = OneBotOutboundMessenger(
        BotRouter(policy, connections), runtime.outbound
    )
    receipt = SendResult(
        delivered=True,
        message_id="-42",
        execution_identity=ExecutionIdentity(Platform.ONEBOT, "111"),
    )
    result = await messenger.verify_history(
        ConversationRef(Platform.ONEBOT, "private", "789"), receipt
    )
    assert (
        result
        is {
            "confirmed": DeliveryHistoryStatus.CONFIRMED,
            "missing": DeliveryHistoryStatus.MISSING,
            "error": DeliveryHistoryStatus.ERROR,
        }[outcome]
    )
    assert receipt.delivered
    assert connection.calls == [("get_msg", {"message_id": -42})]
