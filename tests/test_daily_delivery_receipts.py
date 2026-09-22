from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import (
    DeliveryFailureKind,
    ExecutionIdentity,
    OutboundMessage,
    SendResult,
)
from ironsbot.core.platform import ActorRef, IncomingMessageRef, Platform
from ironsbot.integrations.storage.daily_delivery import SqliteDailyDeliveryStore
from ironsbot.services.identity_link_store import (
    CrossPlatformIdentityLink,
    OfficialIdentity,
)
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.messaging.proactive_delivery import ProactiveDeliverySummary
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
)
from ironsbot.services.private_conversation_routes import PrivateConversationRoutes
from ironsbot.services.seer.lucky_skin_window_delivery import (
    LuckySkinWindowOutboundSender,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_daily_claim_is_atomic_and_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite"
    store = SqliteDailyDeliveryStore(path)
    claims = await asyncio.gather(
        *(asyncio.to_thread(store.claim, "user", "day") for _ in range(8))
    )
    assert sum(claims) == 1
    assert not SqliteDailyDeliveryStore(path).claim("user", "day")
    store.finish("user", "day", "uncertain")
    assert not store.claim("user", "day")
    assert store.claim("user", "tomorrow")
    store.finish("user", "tomorrow", "failed")
    assert store.claim("user", "tomorrow")
    store.finish("user", "tomorrow", "success")
    assert not store.claim("user", "tomorrow")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["success", "failed", "uncertain", "unavailable", "td"]
)
async def test_daily_window_uses_trusted_route_and_receipt_commit(
    tmp_path: Path, outcome: str
) -> None:
    actor = ActorRef(Platform.ONEBOT, "123456")
    principals = IdentityPrincipalService()
    routes = PrivateConversationRoutes(
        onebot_enabled=False, official_accounts=frozenset({"app"})
    )
    link = CrossPlatformIdentityLink(
        actor.id, OfficialIdentity("app", "user", "c2c"), 1
    )
    principals.register_identity_link(link)
    routes.register(link)
    sessions = PortableQuerySessions()
    subscriptions = Mock()
    subscriptions.is_unsubscribed.return_value = outcome == "td"
    delivery = Mock()
    delivery.messenger.capabilities_for.return_value = SimpleNamespace(
        can_send_proactively=outcome != "unavailable"
    )
    select = AsyncMock(return_value=OutboundMessage.from_text("skin details"))
    sends = []

    async def render(
        ctx: MessageInputContext, owner: ActorRef, _result: Any
    ) -> OutboundMessage:
        assert owner == actor
        return sessions.offer_menu(
            ctx,
            PortableMenuSpec(
                choices=(1, 2, 3, 4),
                select=select,
                prompt=OutboundMessage.from_text("four skins"),
                keep_open=True,
            ),
        )

    async def send(
        message: OutboundMessage, targets: Any, **kwargs: Any
    ) -> ProactiveDeliverySummary:
        target = targets[0]
        assert target.platform is Platform.QQ_OFFICIAL and target.account_id == "app"
        assert kwargs["max_attempts"] == 1
        sends.append(message)
        receipt = SendResult(
            outcome == "success",
            message_id="card" if outcome == "success" else None,
            error_code=None if outcome == "success" else "failure",
            failure_kind=DeliveryFailureKind.UNCERTAIN
            if outcome == "uncertain"
            else None,
            execution_identity=ExecutionIdentity(Platform.QQ_OFFICIAL, "app"),
        )
        return ProactiveDeliverySummary(
            (target,) if receipt.delivered else (),
            () if receipt.delivered else (target,),
            (target,) if outcome == "uncertain" else (),
            ((target, receipt),),
        )

    delivery.send = send
    store = SqliteDailyDeliveryStore(tmp_path / "runtime.sqlite")
    sender = LuckySkinWindowOutboundSender(
        delivery,
        subscriptions,
        store,
        routes,
        sessions,
        principals.actor_principal,
        render,
    )
    result = cast("Any", object())
    assert await sender.send_daily_notice(actor, result, day="2026-09-23") == (
        outcome == "success"
    )
    if outcome == "success":
        assert not await sender.send_daily_notice(actor, result, day="2026-09-23")
        target = routes.resolve(
            cast("Any", delivery.messenger.capabilities_for.call_args.args[0])
        )
        incoming = IncomingMessageRef(
            Platform.QQ_OFFICIAL,
            ActorRef(Platform.QQ_OFFICIAL, "c2c", account_id="app"),
            target,
            "choice",
            "1",
        )
        context = MessageInputContext(incoming, mentions_bot=False)
        assert sessions.menu_anchor(context) == "card"
        await sessions.select("1", context)
        select.assert_awaited_once()
    else:
        assert store.claim("lucky:qq:123456", "2026-09-23") == (outcome != "uncertain")
    assert len(sends) == (0 if outcome in {"unavailable", "td"} else 1)
