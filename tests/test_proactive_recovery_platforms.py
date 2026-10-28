from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import BotAccountRef, ConversationRef, Platform
from ironsbot.integrations.qq_official.outbound_messenger import (
    QQOfficialOutboundMessenger,
)
from ironsbot.integrations.storage.proactive_tasks import SqliteProactiveTasks
from ironsbot.services.messaging.delivery_recovery import ProactiveRecovery
from tests.test_onebot_outbound_messenger import _Bot as OneBot
from tests.test_onebot_outbound_messenger import _messenger, _Router
from tests.test_proactive_delivery import _delivery
from tests.test_proactive_recovery import spawn
from tests.test_qq_official_outbound_messenger import _Bot as OfficialBot

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_platform_adapter_offline_then_receipt_does_not_repeat(
    tmp_path: Path,
    platform: Platform,
) -> None:
    available = False
    official = OfficialBot()
    onebot = OneBot()
    transport = (
        _messenger()
        if platform is Platform.ONEBOT
        else QQOfficialOutboundMessenger(
            {"app": True},
            lambda _account: official if available else None,
        )
    )
    account = onebot.self_id if platform is Platform.ONEBOT else "app"
    target = ConversationRef(
        platform,
        "group",
        "3003" if platform is Platform.ONEBOT else "fake-group",
        account_id=account,
    )
    store = SqliteProactiveTasks(tmp_path / "outbox.sqlite")
    delivery, _, _ = _delivery()
    delivery = replace(delivery, outbox=store, messenger=transport)
    first = await delivery.send(
        OutboundMessage.from_text("frozen notice"), (target,), action_name="test"
    )
    assert not first.succeeded
    available = True
    if platform is Platform.ONEBOT:
        router = cast("_Router", cast("Any", transport)._router)
        router.bot = onebot
        router.connections.connect(cast("Any", onebot))
    recovery = ProactiveRecovery(delivery, store, spawn)
    await recovery.connected(BotAccountRef(platform, account))
    await recovery.scan()
    await recovery.scan()
    assert not store.due()
    assert (
        len(onebot.group_messages if platform is Platform.ONEBOT else official.calls)
        == 1
    )
