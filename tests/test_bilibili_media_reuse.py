from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx
import pytest
from qqbot_agent_sdk.dto import QQMessageType

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.qq_official.api_errors import QQOfficialApiError
from ironsbot.integrations.qq_official.media_upload import QQOfficialMediaUpload
from ironsbot.integrations.qq_official.outbound_messenger import (
    QQOfficialOutboundMessenger,
)
from ironsbot.integrations.qq_official.sdk_client import TencentQQClient
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.target_models import BiliPushTargets
from tests.test_bilibili_outbound_delivery import _item
from tests.test_proactive_delivery import _delivery
from tests.test_qq_official_media_upload import _FakeUploader
from tests.test_qq_official_sdk_client import _FakeApi

if TYPE_CHECKING:
    from pathlib import Path

    from qqbot_agent_sdk.api_client import QQApiClient
    from qqbot_agent_sdk.dto import InlineKeyboard, MessageToCreate


@dataclass
class _SelectiveApi(_FakeApi):
    failure: Literal["retryable", "uncertain"] = "retryable"
    image_attempts: dict[str, int] = field(default_factory=dict)

    async def post_group_message(
        self,
        target: str,
        message: MessageToCreate,
        *,
        keyboard: InlineKeyboard | None = None,
    ) -> dict[str, object]:
        if message.msg_type == QQMessageType.RICH_MEDIA:
            self.image_attempts[target] = self.image_attempts.get(target, 0) + 1
            if target == "group-b" and self.image_attempts[target] == 1:
                if self.failure == "uncertain":
                    reason = "response lost"
                    raise httpx.ReadTimeout(reason)
                raise QQOfficialApiError(
                    http_status=429,
                    api_code="40093001",
                    message="temporary limit",
                    trace_id="fictional-trace",
                )
        return await super().post_group_message(target, message, keyboard=keyboard)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["retryable", "uncertain"])
async def test_shared_upload_keeps_per_group_receipts_retries_and_restart_dedup(
    tmp_path: Path, failure: Literal["retryable", "uncertain"]
) -> None:
    first, second = _FakeUploader(), _FakeUploader()
    owner = TaskOwner()
    a = QQOfficialMediaUpload(
        first, tmp_path / "a", account_id="app-a", spawn=owner.create
    )
    b = QQOfficialMediaUpload(
        second, tmp_path / "b", account_id="app-b", spawn=owner.create
    )
    api_a, api_b = _SelectiveApi(failure=failure), _FakeApi()
    clients = {
        "app-a": TencentQQClient(cast("QQApiClient", api_a), a),
        "app-b": TencentQQClient(cast("QQApiClient", api_b), b),
    }
    messenger = QQOfficialOutboundMessenger({"app-a": True, "app-b": True}, clients.get)
    delivery, _, subscriptions = _delivery()
    delivery = replace(delivery, messenger=messenger)
    targets = [
        ConversationRef(Platform.QQ_OFFICIAL, "group", "group-a", account_id="app-a"),
        ConversationRef(Platform.QQ_OFFICIAL, "group", "group-b", account_id="app-a"),
        ConversationRef(Platform.QQ_OFFICIAL, "group", "group-c", account_id="app-b"),
    ]
    item = _item()
    item["id_str"] = "900000000000000001"
    item["modules"]["module_author"]["mid"] = 123
    ledger = SqliteDynamicDeliveryLedger(
        tmp_path / "ledger.sqlite", media_root=tmp_path / "cache"
    )
    sender = BilibiliDynamicOutboundSender(
        delivery, cast("Any", subscriptions), ledger=ledger, combine_images=False
    )
    destinations = BiliPushTargets(targets, [], [], [])
    published = int(time.time())
    await sender.send(item, published, 123, destinations)
    expected = 2 if failure == "retryable" else 1
    assert api_a.image_attempts == {"group-a": 1, "group-b": expected}
    assert len(first.calls) == 1
    assert len(second.calls) == 1
    assert not a._batches and not b._batches
    with SqliteDatabase(ledger.path).connect() as db:
        rows = db.execute(
            "SELECT target,state,result,attempts FROM stages WHERE stage='image:1'"
        ).fetchall()
    results = {
        json.loads(target)["id"]: (state, json.loads(result), n)
        for target, state, result, n in rows
    }
    assert results["group-a"][0] == "success"
    assert results["group-c"][0] == "success"
    assert results["group-a"][1]["message_id"]
    assert results["group-c"][1]["message_id"]
    assert results["group-b"][2] == expected
    if failure == "uncertain":
        assert results["group-b"][0] == "uncertain"
        assert results["group-b"][1]["failure_kind"] == DeliveryFailureKind.UNCERTAIN
    else:
        assert results["group-b"][0] == "success"
        assert (
            results["group-b"][1]["message_id"] != results["group-a"][1]["message_id"]
        )
    await sender.send(item, published, 123, destinations, resume=True)
    assert api_a.image_attempts == {"group-a": 1, "group-b": expected}
    assert len(first.calls) == 1
